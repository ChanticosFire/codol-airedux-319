"""Call an arbitrary function on the game's MAIN thread, safely.

`ring_bridge.invoke_sequence` suspends the window-message thread, but the network
and connect code run on the WinMain thread, so that path never reached them
(proven by sentinel experiments).  `launch_1649370.py --main-call` does it right
by suspending the main thread and hijacking its context; this tool exposes the
same mechanism against an already-running client.

    python tools/main_call_1649370.py --target 0x5BE730
    python tools/main_call_1649370.py --target 0x5BE730 --ecx connection
    python tools/main_call_1649370.py --target 0x5BE730 --arg 0 --arg 1
    python tools/main_call_1649370.py --probe
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)

k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenThread.restype = W.HANDLE
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.FlushInstructionCache.restype = W.BOOL
k32.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
k32.SetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
wow64_get.argtypes = [W.HANDLE, C.c_void_p]
wow64_set.argtypes = [W.HANDLE, C.c_void_p]

STAGE = 0xE59D20
NET_STATE = 0x76446B0
CONN_ENCODED = 0x331C0C8
CONN_XOR = 0xD362501F
UI_STATE = 0x84ABA50

CONTEXT_SIZE, EIP_OFFSET, ESP_OFFSET, ECX_OFFSET = 716, 184, 196, 172
CONTEXT_FLAGS = 0x00010001


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def first_thread(pid: int) -> int:
    TH32CS_SNAPTHREAD = 0x4

    class THREADENTRY32(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                    ("th32ThreadID", W.DWORD), ("th32OwnerProcessID", W.DWORD),
                    ("tpBasePri", C.c_long), ("tpDeltaPri", C.c_long), ("dwFlags", W.DWORD)]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap in (0, -1):
        raise SystemExit("CreateToolhelp32Snapshot failed")
    found: list[int] = []
    entry = THREADENTRY32()
    entry.dwSize = C.sizeof(THREADENTRY32)
    try:
        if k32.Thread32First(snap, C.byref(entry)):
            while True:
                if entry.th32OwnerProcessID == pid:
                    found.append(int(entry.th32ThreadID))
                if not k32.Thread32Next(snap, C.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    if not found:
        raise SystemExit("no threads")
    return found[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=lambda v: int(v, 0), required=False)
    ap.add_argument("--ecx", default=None, help="'connection' or a hex value")
    ap.add_argument("--arg", type=lambda v: int(v, 0), action="append", default=[],
                    help="cdecl-style argument pushed right-to-left; repeat in order")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--settle", type=float, default=3.0)
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, n: int) -> bytes | None:
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, n, C.byref(got)) or got.value != n:
            return None
        return buf.raw

    def u32(va: int) -> int | None:
        d = read(va, 4)
        return struct.unpack("<I", d)[0] if d else None

    def w32(va: int, value: int) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(struct.pack("<I", value), 4),
                                          4, C.byref(got))) and got.value == 4

    encoded = u32(CONN_ENCODED) or 0
    connection = encoded ^ CONN_XOR
    report: dict = {"pid": pid, "stage": u32(STAGE), "net_state": u32(NET_STATE),
                    "ui_state": u32(UI_STATE), "connection": hex(connection),
                    "connection_valid": 0x10000 <= connection < 0x7FFF0000}
    if report["connection_valid"]:
        report["adr_14"] = hex(u32(connection + 0x14) or 0)
        report["chan_28"] = hex(u32(connection + 0x28) or 0)
    if args.probe or args.target is None:
        print(json.dumps(report, indent=2))
        return 0

    ecx = None
    if args.ecx:
        ecx = connection if args.ecx == "connection" else int(args.ecx, 0)

    tid = first_thread(pid)
    thread = k32.OpenThread(0x1F03FF, False, tid)
    if not thread:
        raise SystemExit(f"OpenThread failed err={C.get_last_error()}")
    report["tid"] = tid
    report["target"] = hex(args.target)
    report["ecx"] = hex(ecx) if ecx is not None else None
    report["args"] = [hex(a) for a in args.arg]

    try:
        if k32.SuspendThread(thread) == 0xFFFFFFFF:
            raise SystemExit(f"SuspendThread failed err={C.get_last_error()}")
        try:
            storage = C.create_string_buffer(CONTEXT_SIZE + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, CONTEXT_SIZE)
            C.c_uint32.from_address(aligned).value = CONTEXT_FLAGS
            if not wow64_get(thread, C.c_void_p(aligned)):
                report["status"] = "get_context_failed"
                report["error"] = C.get_last_error()
                raise SystemExit(1)
            original_eip = C.c_uint32.from_address(aligned + EIP_OFFSET).value
            original_esp = C.c_uint32.from_address(aligned + ESP_OFFSET).value
            report.update(original_eip=hex(original_eip), original_esp=hex(original_esp))

            cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40) or 0)
            if not cave:
                report["status"] = "alloc_failed"
                raise SystemExit(1)
            result_slot = cave + 0x200
            report["cave"] = hex(cave)

            code = b"\x60"                                    # pushad
            if ecx is not None:
                code += b"\xb9" + struct.pack("<I", ecx)      # mov ecx,imm
            for value in reversed(args.arg):
                code += b"\x68" + struct.pack("<I", value)    # push value
            rel = (args.target - (cave + len(code) + 5)) & 0xFFFFFFFF
            code += b"\xe8" + struct.pack("<I", rel)          # call target
            if args.arg:
                code += b"\x83\xc4" + struct.pack("<B", 4 * len(args.arg))   # add esp,N
            code += b"\xa3" + struct.pack("<I", result_slot)  # mov [slot],eax
            code += b"\x61\xc3"                               # popad; ret
            report["code"] = code.hex()

            got = C.c_size_t()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave),
                                           C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(got)) or got.value != len(code)):
                report["status"] = "cave_write_failed"
                raise SystemExit(1)
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if not w32(original_esp - 4, original_eip):
                report["status"] = "return_write_failed"
                raise SystemExit(1)
            C.c_uint32.from_address(aligned + ESP_OFFSET).value = original_esp - 4
            C.c_uint32.from_address(aligned + EIP_OFFSET).value = cave
            if ecx is not None:
                C.c_uint32.from_address(aligned + ECX_OFFSET).value = ecx
            if not wow64_set(thread, C.c_void_p(aligned)):
                report["status"] = "set_context_failed"
                report["error"] = C.get_last_error()
                raise SystemExit(1)
            report["status"] = "armed"
        finally:
            k32.ResumeThread(thread)
    finally:
        k32.CloseHandle(thread)

    time.sleep(args.settle)
    report["result_eax"] = hex(u32(result_slot) or 0)
    report["after"] = {"stage": u32(STAGE), "net_state": u32(NET_STATE),
                       "ui_state": u32(UI_STATE)}
    after_enc = u32(CONN_ENCODED) or 0
    after_conn = after_enc ^ CONN_XOR
    if 0x10000 <= after_conn < 0x7FFF0000:
        report["after"].update(adr_14=hex(u32(after_conn + 0x14) or 0),
                               chan_28=hex(u32(after_conn + 0x28) or 0))
    report["alive"] = report["after"]["stage"] is not None
    print(json.dumps(report, indent=2))
    return 0 if report["alive"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
