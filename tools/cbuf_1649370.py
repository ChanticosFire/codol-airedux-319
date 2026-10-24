"""Append a console command to CODOL's native Cbuf and let the engine consume it.

Mirrors the proven injector in launch_1649370.py but runs standalone against an
already-running client, so a live lobby can be driven without relaunching.

Native layout:
    0x76595A4  descriptor {pointer, capacity, length}
    0x33821B0  ring buffer, capacity 0x20000
    0x81A55A0  critical section, dword[2] == recursion count

The main thread is suspended only for the duration of the write, then resumed so
the engine's own consumer picks the text up.

    python tools/cbuf_1649370.py --command "echo CBUF_OK"
    python tools/cbuf_1649370.py --command "map mp_crash_tropical"
    python tools/cbuf_1649370.py --probe
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
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenThread.restype = W.HANDLE
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD

DESCRIPTOR = 0x76595A4
BUFFER = 0x33821B0
CAPACITY = 0x20000
LOCK = 0x81A55A0
STAGE = 0xE59D20
UI_STATE = 0x84ABA50


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main_thread_ids(pid: int) -> list[int]:
    TH32CS_SNAPTHREAD = 0x4

    class THREADENTRY32(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                    ("th32ThreadID", W.DWORD), ("th32OwnerProcessID", W.DWORD),
                    ("tpBasePri", C.c_long), ("tpDeltaPri", C.c_long), ("dwFlags", W.DWORD)]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap in (0, -1):
        return []
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
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", default="")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--wait-stage", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=90.0)
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

    tids = main_thread_ids(pid)
    probe = {"pid": pid, "threads": len(tids), "first_tid": tids[0] if tids else None,
             "stage": u32(STAGE), "ui_state": u32(UI_STATE)}
    descriptor = read(DESCRIPTOR, 12)
    if descriptor:
        pointer, capacity, length = struct.unpack("<3I", descriptor)
        probe.update(descriptor={"pointer": hex(pointer), "capacity": capacity, "length": length,
                                "match": pointer == BUFFER and capacity == CAPACITY})
    lock = read(LOCK, 16)
    if lock:
        probe["lock_recursion"] = struct.unpack("<4I", lock)[2]
    if args.probe or not args.command:
        print(json.dumps(probe, indent=2))
        return 0

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if (u32(STAGE) or 0) >= args.wait_stage:
            break
        time.sleep(0.5)

    if not tids:
        raise SystemExit("no threads")
    thread = k32.OpenThread(0x1F03FF, False, tids[0])
    if not thread:
        raise SystemExit(f"OpenThread failed err={C.get_last_error()}")

    payload = ("\n" + args.command + "\n").encode("ascii") + b"\0"
    result = {**probe, "command": args.command, "status": "waiting", "payload": len(payload)}
    try:
        for _ in range(30):
            descriptor = read(DESCRIPTOR, 12)
            if not descriptor:
                result["status"] = "descriptor_unreadable"
                break
            pointer, capacity, length = struct.unpack("<3I", descriptor)
            if pointer != BUFFER or capacity != CAPACITY or length + len(payload) > CAPACITY:
                result["status"] = "descriptor_mismatch"
                result["descriptor"] = {"pointer": hex(pointer), "capacity": capacity, "length": length}
                break
            lock = read(LOCK, 16)
            if lock and struct.unpack("<4I", lock)[2]:
                time.sleep(0.2)
                continue
            if k32.SuspendThread(thread) == 0xFFFFFFFF:
                result["status"] = "suspend_failed"
                break
            try:
                descriptor = read(DESCRIPTOR, 12)
                pointer, capacity, length = struct.unpack("<3I", descriptor)
                if pointer != BUFFER or capacity != CAPACITY or length + len(payload) > CAPACITY:
                    result["status"] = "descriptor_changed"
                    break
                wrote = C.c_size_t()
                if (not k32.WriteProcessMemory(handle, C.c_void_p(BUFFER + length),
                                               C.create_string_buffer(payload, len(payload)),
                                               len(payload), C.byref(wrote))
                        or wrote.value != len(payload)):
                    result["status"] = "write_failed"
                    result["error"] = C.get_last_error()
                    break
                new_length = length + len(payload)
                if (not k32.WriteProcessMemory(handle, C.c_void_p(DESCRIPTOR + 8),
                                               C.create_string_buffer(struct.pack("<I", new_length), 4),
                                               4, C.byref(wrote)) or wrote.value != 4):
                    result["status"] = "length_failed"
                    result["error"] = C.get_last_error()
                    break
                result.update(status="injected", old_length=length, new_length=new_length)
                time.sleep(0.5)
            finally:
                k32.ResumeThread(thread)
            break
        if result["status"] == "waiting":
            result["status"] = "stage_timeout"
    finally:
        k32.CloseHandle(thread)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "injected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
