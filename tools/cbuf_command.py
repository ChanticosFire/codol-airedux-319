"""Inject one console command into the client's native Cbuf at runtime.

The engine keeps its command buffer at `0x33821B0` (capacity `0x20000`) and a
`{pointer, capacity, length}` descriptor at `0x76595A4`.  Appending a command
there and bumping the length makes the engine execute it on the next frame, on
the window thread.

    python tools/cbuf_command.py --command "map mp_strike_sh"
    python tools/cbuf_command.py --command "devmap mp_strike_sh" --wait-stage
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
CBUF_BUFFER = 0x33821B0
CBUF_DESCRIPTOR = 0x76595A4
CBUF_LOCK = 0x81A55A0
STAGE = 0xE59D20

k32 = sc.k32
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                   C.POINTER(C.c_size_t)]
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD

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
    parser.add_argument("--command", required=True)
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--wait-stage", action="store_true",
                        help="wait until stage >= 4 before injecting")
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = k32.OpenProcess(0x0438, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "command": args.command}

    def read(va: int, count: int):
        buffer = C.create_string_buffer(count)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buffer, count, C.byref(got)) \
                or got.value != count:
            return None
        return buffer.raw

    def u32(va: int):
        data = read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    try:
        if args.wait_stage:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if (u32(STAGE) or 0) >= 4:
                    break
                time.sleep(0.5)
        row["stage"] = u32(STAGE)
        payload = ("\n" + args.command + "\n").encode("ascii") + b"\0"
        tid = window_thread(args.window)
        thread = k32.OpenThread(0x1F03FF, False, tid)
        injected = False
        for attempt in range(1, 31):
            descriptor = read(CBUF_DESCRIPTOR, 12)
            if not descriptor:
                row.update(status="descriptor_unreadable")
                break
            pointer, capacity, length = struct.unpack("<3I", descriptor)
            if pointer != CBUF_BUFFER or capacity != 0x20000 or length + len(payload) > capacity:
                row.update(status="descriptor_mismatch", pointer=hex(pointer),
                           capacity=capacity, length=length)
                break
            lock = read(CBUF_LOCK, 16)
            if not lock:
                row.update(status="lock_unreadable")
                break
            if struct.unpack("<4I", lock)[2]:
                time.sleep(0.2)
                continue
            if k32.SuspendThread(thread) == 0xFFFFFFFF:
                row.update(status="suspend_failed", error=C.get_last_error())
                break
            try:
                descriptor = read(CBUF_DESCRIPTOR, 12)
                pointer, capacity, length = struct.unpack("<3I", descriptor)
                if pointer != CBUF_BUFFER or capacity != 0x20000:
                    row.update(status="descriptor_changed")
                    break
                wrote = C.c_size_t()
                target = CBUF_BUFFER + length
                ok = k32.WriteProcessMemory(
                    handle, C.c_void_p(target),
                    C.create_string_buffer(payload, len(payload)),
                    len(payload), C.byref(wrote))
                if not ok or wrote.value != len(payload):
                    row.update(status="write_failed", error=C.get_last_error())
                    break
                new_length = length + len(payload)
                ok = k32.WriteProcessMemory(
                    handle, C.c_void_p(CBUF_DESCRIPTOR + 8),
                    C.create_string_buffer(struct.pack("<I", new_length), 4),
                    4, C.byref(wrote))
                if not ok or wrote.value != 4:
                    row.update(status="length_failed", error=C.get_last_error())
                    break
                row.update(status="injected", attempt=attempt, old_length=length,
                           new_length=new_length, thread=tid)
                injected = True
                time.sleep(0.5)
            finally:
                k32.ResumeThread(thread)
            break
        if not injected and "status" not in row:
            row["status"] = "timeout"
        k32.CloseHandle(thread)
    finally:
        k32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
