"""Create the missing UDP transport channel on a live client, then send getchallenge.

`StringToAdr("localhost")` leaves `adr+0x14 == 0x9D` (the in-process loopback
marker) and the connect path never calls `0x621E50`, so `0x622040` walks off the
channel table and returns -7.  Every send silently dies there.  This tool
reproduces the fix from `launch_1649370.py::_transport_connect_injector` but runs
standalone against an already-logged-in client, because injecting during startup
(`--transport-connect`) crashes the client before the connection object exists.

Sequence, all inside one main-thread suspend window:
    1. adr = connection+0x14  <- {type:4, 127.0.0.1, htons(port), 0, 0, 0, 0x9D}
    2. buf = "xx"
    3. [0x76446B0] = 3                       (net_state = 3)
    4. call 0x621E50(adr, buf, 2)            -> fills adr+0x14 with the channel id
    5. call 0x5C05F0(connection)             -> sends getchallenge

Success criteria: `adr+0x14 != 0x9D` and `channel(+0x28) != 0`, and the game
server logs a `getchallenge`.

    python tools/transport_connect_1649370.py --probe
    python tools/transport_connect_1649370.py --port 28969
    python tools/transport_connect_1649370.py --port 28969 --dry-run
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import socket
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
HOST_SINGLETON = 0xE85C68
CREATE_CHANNEL = 0x621E50
SEND_CHALLENGE = 0x5C05F0

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
        raise SystemExit("no threads found")
    return found[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=28969, help="loopback UDP port written into adr")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--settle", type=float, default=8.0)
    ap.add_argument("--ring", action="store_true",
                    help="loopback-ring mode: adr type=2, no channel creation, only 0x5C05F0")
    ap.add_argument("--no-state", action="store_true",
                    help="do not write net_state=3 before the call")
    ap.add_argument("--send-only", action="store_true",
                    help="leave adr untouched and only call 0x5C05F0 (use after a live channel exists)")
    ap.add_argument("--dry-run", action="store_true", help="inspect only, do not arm the cave")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, count: int) -> bytes | None:
        buf = C.create_string_buffer(count)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, count, C.byref(got)) or got.value != count:
            return None
        return buf.raw

    def u32(va: int) -> int | None:
        data = read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    def w32(va: int, value: int) -> bool:
        wrote = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(struct.pack("<I", value), 4),
                                          4, C.byref(wrote))) and wrote.value == 4

    report: dict = {"pid": pid, "port": args.port}

    def snapshot() -> dict:
        encoded = u32(CONN_ENCODED) or 0
        conn = encoded ^ CONN_XOR
        row = {"stage": u32(STAGE), "net_state": u32(NET_STATE),
               "encoded_conn": hex(encoded), "connection": hex(conn),
               "valid": 0x10000 <= conn < 0x7FFF0000}
        if row["valid"]:
            row["adr_14"] = hex(u32(conn + 0x14) or 0)
            row["channel_28"] = hex(u32(conn + 0x28) or 0)
            row["state_100260"] = u32(conn + 0x100260)
        return row

    report["before"] = snapshot()
    if args.probe:
        print(json.dumps(report, indent=2))
        return 0

    connection = int(report["before"]["connection"], 16) if report["before"]["valid"] else 0
    if not connection:
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if (u32(STAGE) or 0) >= 4:
                encoded = u32(CONN_ENCODED) or 0
                candidate = encoded ^ CONN_XOR
                if 0x10000 <= candidate < 0x7FFF0000:
                    connection = candidate
                    break
            time.sleep(0.5)
    if not connection:
        report["status"] = "connection_not_ready"
        print(json.dumps(report, indent=2))
        return 1
    report["connection"] = hex(connection)

    tid = first_thread(pid)
    thread = k32.OpenThread(0x1F03FF, False, tid)
    if not thread:
        raise SystemExit(f"OpenThread failed err={C.get_last_error()}")
    report["tid"] = tid

    adr = connection + 0x14
    host = u32(HOST_SINGLETON) or 0
    biz = (u32(host + 0x1F0) or 0) if host else 0
    gate = (u32(biz + 0x18) or 0) if biz else 0
    report.update(host=hex(host), biz=hex(biz), gate_before=gate)

    adr_bytes = struct.pack("<I4sHHIII",
                            (2 if args.ring else 4),
                            (b"\0\0\0\0" if args.ring else b"\x7f\x00\x00\x01"),
                            socket.htons(args.port), 0, 0, 0, 0x9D)
    report["adr_bytes"] = adr_bytes.hex()
    report["mode"] = "ring" if args.ring else "transport"
    report["plan"] = {"adr": hex(adr), "net_state": 3,
                      "call_create_channel": None if args.ring else hex(CREATE_CHANNEL),
                      "call_send_challenge": hex(SEND_CHALLENGE)}
    if args.dry_run:
        report["status"] = "dry_run"
        print(json.dumps(report, indent=2))
        return 0

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
            buf = cave + 0x100
            result_slot = cave + 0x200
            report.update(cave=hex(cave), buf=hex(buf), result_slot=hex(result_slot))

            if biz and gate != 1:
                if not w32(biz + 0x18, 1):
                    report["status"] = "gate_write_failed"
                    raise SystemExit(1)
                report["gate_after"] = u32(biz + 0x18)

            wrote = C.c_size_t()
            if args.send_only:
                report["adr_write"] = "skipped"
            elif (not k32.WriteProcessMemory(handle, C.c_void_p(adr),
                                             C.create_string_buffer(adr_bytes, len(adr_bytes)),
                                             len(adr_bytes), C.byref(wrote))
                  or wrote.value != len(adr_bytes)):
                report["status"] = "adr_write_failed"
                report["error"] = C.get_last_error()
                raise SystemExit(1)
            if (not k32.WriteProcessMemory(handle, C.c_void_p(buf), C.create_string_buffer(b"xx\0", 3),
                                           3, C.byref(wrote)) or wrote.value != 3):
                report["status"] = "buf_write_failed"
                raise SystemExit(1)
            if args.no_state:
                report["net_state_write"] = "skipped"
            elif not w32(NET_STATE, 3):
                report["status"] = "state_write_failed"
                raise SystemExit(1)
            else:
                report["net_state_write"] = 3

            def call_rel(target: int, at: int) -> bytes:
                return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

            code = b"\x60\x6a\x02" if not (args.ring or args.send_only) else b"\x60"
            if not (args.ring or args.send_only):
                code += b"\x68" + struct.pack("<I", buf)                    # push buf
                code += b"\x68" + struct.pack("<I", adr)                    # push adr
                code += call_rel(CREATE_CHANNEL, cave + len(code))
                code += b"\x83\xc4\x0c"                                     # add esp,0xc
                code += b"\xa3" + struct.pack("<I", result_slot)            # mov [slot],eax
            code += b"\xb9" + struct.pack("<I", connection)                 # mov ecx,connection
            code += call_rel(SEND_CHALLENGE, cave + len(code))
            code += b"\x61\xc3"                                             # popad; ret
            report["code"] = code.hex()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave),
                                           C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(wrote)) or wrote.value != len(code)):
                report["status"] = "cave_write_failed"
                raise SystemExit(1)
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if not w32(original_esp - 4, original_eip):
                report["status"] = "return_write_failed"
                raise SystemExit(1)
            C.c_uint32.from_address(aligned + ESP_OFFSET).value = original_esp - 4
            C.c_uint32.from_address(aligned + EIP_OFFSET).value = cave
            C.c_uint32.from_address(aligned + ECX_OFFSET).value = connection
            if not wow64_set(thread, C.c_void_p(aligned)):
                report["status"] = "set_context_failed"
                report["error"] = C.get_last_error()
                raise SystemExit(1)
            report["status"] = "armed"
        finally:
            k32.ResumeThread(thread)
        time.sleep(args.settle)
        report["result_eax"] = hex(u32(result_slot) or 0)
        report["after"] = snapshot()
        after_adr = read(adr, 0x18)
        report["adr_after"] = after_adr.hex() if after_adr else None
        report["status"] = "done"
    finally:
        k32.CloseHandle(thread)
        k32.CloseHandle(handle)

    if args.ring:
        ok = report.get("after", {}).get("stage") is not None
        report["ring_mode"] = True
    else:
        ok = (report.get("after", {}).get("adr_14") not in (None, "0x9d", "0x0")
              and report.get("after", {}).get("channel_28") not in (None, "0x0"))
    report["channel_created"] = ok
    print(json.dumps(report, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
