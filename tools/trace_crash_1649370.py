"""Attach a minimal debugger to the offline 1649370 client and record a crash.

The launcher's in-process host catches the access violation first, so WER does
not create a dump.  This tool attaches with DebugActiveProcess, forwards every
event, and on a second-chance exception records the 32-bit context, the raw
stack, the EBP chain and a small disassembly window around EIP.

    python tools/trace_crash_1649370.py --seconds 180 --out runs/crash-trace.json
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.DebugActiveProcess.argtypes = [W.DWORD]
k32.DebugActiveProcess.restype = W.BOOL
k32.DebugActiveProcessStop.argtypes = [W.DWORD]
k32.DebugActiveProcessStop.restype = W.BOOL
k32.DebugSetProcessKillOnExit.argtypes = [W.BOOL]
k32.DebugSetProcessKillOnExit.restype = W.BOOL
k32.WaitForDebugEvent.argtypes = [C.c_void_p, W.DWORD]
k32.WaitForDebugEvent.restype = W.BOOL
k32.ContinueDebugEvent.argtypes = [W.DWORD, W.DWORD, W.DWORD]
k32.ContinueDebugEvent.restype = W.BOOL
k32.OpenThread.restype = W.HANDLE
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]

EXCEPTION_DEBUG_EVENT = 1
EXIT_PROCESS_DEBUG_EVENT = 5
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
CONTEXT_SIZE = 716
CONTEXT_FLAGS = 0x00010007  # i386 | CONTROL | INTEGER | SEGMENTS


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [
        ("dwDebugEventCode", W.DWORD),
        ("dwProcessId", W.DWORD),
        ("dwThreadId", W.DWORD),
        ("u", C.c_byte * 160),
    ]


def find_pid() -> int:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
        capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return 0


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    ok = k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[:got.value] if ok else b""


def context_of(thread_id: int) -> dict:
    thread = k32.OpenThread(0x1F03FF, False, thread_id)
    if not thread:
        return {}
    try:
        storage = C.create_string_buffer(CONTEXT_SIZE + 16)
        aligned = (C.addressof(storage) + 15) & ~15
        C.memset(aligned, 0, CONTEXT_SIZE)
        C.c_uint32.from_address(aligned).value = CONTEXT_FLAGS
        get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
        get.argtypes = [W.HANDLE, C.c_void_p]
        get.restype = W.BOOL
        if not get(thread, C.c_void_p(aligned)):
            return {}
        data = C.string_at(aligned, CONTEXT_SIZE)
        # i386 CONTEXT layout offsets
        names = {"edi": 0x9C, "esi": 0xA0, "ebx": 0xA4, "edx": 0xA8, "ecx": 0xAC,
                 "eax": 0xB0, "ebp": 0xB4, "eip": 0xB8, "esp": 0xC4}
        return {name: struct.unpack_from("<I", data, off)[0] for name, off in names.items()}
    finally:
        k32.CloseHandle(thread)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--out", default="runs/crash-trace.json")
    args = parser.parse_args()

    pid = 0
    deadline = time.monotonic() + 60
    while not pid and time.monotonic() < deadline:
        pid = find_pid()
        time.sleep(0.5)
    if not pid:
        raise SystemExit("client not running")

    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    result: dict = {"pid": pid, "utc": datetime.now(timezone.utc).isoformat(),
                    "attached": False, "exceptions": [], "exit": None}
    if not k32.DebugActiveProcess(pid):
        result["error"] = f"DebugActiveProcess failed: {C.get_last_error()}"
    else:
        result["attached"] = True
        k32.DebugSetProcessKillOnExit(False)
        event = DEBUG_EVENT()
        end = time.monotonic() + args.seconds
        try:
            while time.monotonic() < end:
                if not k32.WaitForDebugEvent(C.byref(event), 1000):
                    continue
                code = event.dwDebugEventCode
                tid = event.dwThreadId
                continue_status = DBG_CONTINUE
                if code == EXCEPTION_DEBUG_EVENT:
                    # EXCEPTION_DEBUG_INFO at u[0]
                    first = struct.unpack_from("<I", bytes(event.u), 0)[0]
                    code_value = struct.unpack_from("<I", bytes(event.u), 4)[0]
                    flags = struct.unpack_from("<I", bytes(event.u), 8)[0]
                    address = struct.unpack_from("<I", bytes(event.u), 16)[0]
                    count = struct.unpack_from("<I", bytes(event.u), 24)[0]
                    params = [struct.unpack_from("<I", bytes(event.u), 28 + 4 * i)[0]
                              for i in range(min(count, 4))]
                    if code_value == 0xC0000005 and first == 0:
                        ctx = context_of(tid)
                        stack = read(handle, (ctx.get("esp", 0) - 0x40) & 0xFFFFFFFF, 0x400)
                        chain = []
                        frame = ctx.get("ebp", 0)
                        for _ in range(16):
                            if not frame or frame < 0x10000:
                                break
                            blob = read(handle, frame, 8)
                            if len(blob) != 8:
                                break
                            nxt, ret = struct.unpack("<II", blob)
                            chain.append({"frame": hex(frame), "return": hex(ret)})
                            if nxt <= frame:
                                break
                            frame = nxt
                        result["exceptions"].append({
                            "first_chance": first, "code": hex(code_value),
                            "flags": hex(flags), "address": hex(address),
                            "params": [hex(p) for p in params],
                            "context": {k: hex(v) for k, v in ctx.items()},
                            "stack_hex": stack.hex(),
                            "ebp_chain": chain,
                            "eip_bytes": read(handle, address & 0xFFFFF000, 0x1000)[
                                (address & 0xFFF):(address & 0xFFF) + 64].hex(),
                        })
                        # Stop the target and let the launcher observe the exit.
                        continue_status = DBG_EXCEPTION_NOT_HANDLED
                elif code == EXIT_PROCESS_DEBUG_EVENT:
                    result["exit"] = struct.unpack_from("<I", bytes(event.u), 0)[0]
                    k32.ContinueDebugEvent(event.dwProcessId, event.dwThreadId, DBG_CONTINUE)
                    break
                k32.ContinueDebugEvent(event.dwProcessId, event.dwThreadId, continue_status)
        finally:
            k32.DebugActiveProcessStop(pid)
    k32.CloseHandle(handle)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("pid", "attached", "exit", "error")
                      if k in result}, ensure_ascii=False))
    print(f"exceptions={len(result['exceptions'])} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
