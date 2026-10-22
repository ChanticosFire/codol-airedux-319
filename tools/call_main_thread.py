"""Invoke one no-argument window-thread function inside Build 1649370.

Earlier rounds proved that calling the room start entry from a *remote thread*
either blocks or corrupts the engine state.  The engine expects room/UI work on
the thread that owns the window, so this tool suspends that thread, points its
EIP at a cave that runs `pushad; <call>; popad; ret`, and resumes it.  The cave
returns to the exact instruction the thread was suspended at.

Only allocation plus one call is performed; no game code is patched.  Use it
with a bounded wait, then read the process state from outside.

    python tools/call_main_thread.py --target 0x62f840 --ecx-room --args 1 0 0
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import time
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_SIZE = 716
EIP_OFFSET = 184
ESP_OFFSET = 196
CONTEXT_FLAGS = 0x00010003  # CONTEXT_i386 | CONTROL | INTEGER

user32 = C.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD


def window_thread(class_name: str) -> int:
    hwnd = user32.FindWindowW(class_name, None)
    if not hwnd:
        raise OSError(f"no window of class {class_name}")
    return user32.GetWindowThreadProcessId(hwnd, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--ecx-room", action="store_true",
                        help="set ECX to [0x82E13FC] (frontend room object)")
    parser.add_argument("--ecx", type=lambda value: int(value, 0), default=None)
    parser.add_argument("--eax", type=lambda value: int(value, 0), default=None,
                        help="set EAX before the call (slot pointer for 0x7FAF50)")
    parser.add_argument("--args", nargs="*", type=lambda value: int(value, 0), default=[])
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--settle", type=float, default=2.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    k32 = sc.k32
    k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenThread.restype = W.HANDLE
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    k32.SetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
    k32.SetThreadContext.restype = W.BOOL
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]

    pid = sc.find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    tid = window_thread(args.window)
    thread = k32.OpenThread(0x1F03FF, False, tid)
    if not thread:
        raise OSError(f"OpenThread failed for tid {tid}: {C.get_last_error()}")
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(),
           "pid": pid, "tid": tid, "target": hex(args.target),
           "args": [hex(value) for value in args.args]}
    try:
        if k32.SuspendThread(thread) == 0xFFFFFFFF:
            raise OSError(f"SuspendThread failed: {C.get_last_error()}")
        storage = C.create_string_buffer(CONTEXT_SIZE + 16)
        aligned = (C.addressof(storage) + 15) & ~15
        C.memset(aligned, 0, CONTEXT_SIZE)
        C.c_uint32.from_address(aligned).value = CONTEXT_FLAGS
        wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
        wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
        wow64_get.argtypes = [W.HANDLE, C.c_void_p]
        wow64_set.argtypes = [W.HANDLE, C.c_void_p]
        if not wow64_get(thread, C.c_void_p(aligned)):
            raise OSError(f"GetThreadContext failed: {C.get_last_error()}")
        original_eip = C.c_uint32.from_address(aligned + EIP_OFFSET).value
        original_esp = C.c_uint32.from_address(aligned + ESP_OFFSET).value
        row["original"] = {"eip": hex(original_eip), "esp": hex(original_esp)}

        ecx_value = 0
        if args.ecx_room:
            ecx_value = sc.u32(handle, 0x82E13FC)
        elif args.ecx is not None:
            ecx_value = args.ecx
        row["ecx"] = hex(ecx_value)
        row["eax"] = hex(args.eax or 0)

        cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
        if not cave:
            raise OSError("VirtualAllocEx failed")
        code = bytearray(b"\x60")                      # pushad
        if args.eax:
            code += b"\xb8" + struct.pack("<I", args.eax)   # mov eax, imm32
        if ecx_value:
            code += b"\xb9" + struct.pack("<I", ecx_value)   # mov ecx, imm32
        for value in reversed(args.args):
            code += b"\x68" + struct.pack("<I", value)       # push imm32 (argN..arg0)
        call_position = len(code)
        code += b"\xe8\x00\x00\x00\x00"                # call target
        struct.pack_into("<i", code, call_position + 1,
                         args.target - (cave + call_position + 5))
        code += b"\x61\xc3"                            # popad; ret
        sc.w(handle, cave, bytes(code))
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
        row["cave"] = hex(cave)

        return_slot = original_esp - 4
        sc.w(handle, return_slot, struct.pack("<I", original_eip))
        C.c_uint32.from_address(aligned + ESP_OFFSET).value = return_slot
        C.c_uint32.from_address(aligned + EIP_OFFSET).value = cave
        if not wow64_set(thread, C.c_void_p(aligned)):
            raise OSError(f"SetThreadContext failed: {C.get_last_error()}")
        k32.ResumeThread(thread)
        row["resumed"] = True
        time.sleep(args.settle)
        row["process_alive_after"] = bool(C.WinDLL("kernel32").OpenProcess(0x1000, False, pid))
    finally:
        try:
            k32.CloseHandle(thread)
        except Exception:
            pass
        sc.k32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(json.dumps(row, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
