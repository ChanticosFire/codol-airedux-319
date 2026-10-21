"""Inject one console command into a running CODOL 1649370 process.

The offline room's Ready control is inert.  The wrapper's ``--room-command``
covers the first command; this standalone tool lets a later experiment queue a
second command (for example ``map`` after ``devmap``) without restarting the
client.  It finds the game's main thread from the run log, suspends it, appends
text to the original Cbuf, read back the length, and resumes.

It never calls a game function or edits a game/community file.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

RUNS = Path(r"E:\GAME\COD\1649370\workspaces\offline-runs")
BUFFER_POINTER = 0x33821B0
BUFFER_CAPACITY = 0x20000
DESCRIPTOR = 0x76595A4
LOCK = 0x81A55A0
ROOM_POINTER = 0x82E13FC

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenThread.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD
k32.CloseHandle.argtypes = [W.HANDLE]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return 0


def main_thread_from_session(session: str) -> int:
    events = RUNS / session / "events.jsonl"
    if not events.is_file():
        return 0
    for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("milestone") == "Com Init" and isinstance(row.get("tid"), int):
            return row["tid"]
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", help="ASCII console command, for example 'map mp_strike_sh'")
    parser.add_argument("--session", help="offline run name used to recover the main-thread id")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--no-room-wait", action="store_true",
                        help="inject without waiting for a valid room (for example connect in the lobby)")
    args = parser.parse_args()

    pid = args.pid or find_pid()
    if not pid:
        raise SystemExit("game process not found")
    tid = main_thread_from_session(args.session) if args.session else 0
    if not tid:
        raise SystemExit("main-thread id not found; pass --session with a run that logged Com Init")
    handle = k32.OpenProcess(0x0438, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    thread = k32.OpenThread(0x0002, False, tid)
    if not thread:
        raise SystemExit(f"OpenThread failed: {C.get_last_error()}")

    def read(va: int, count: int):
        buffer = C.create_string_buffer(count)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buffer, count, C.byref(got)) or got.value != count:
            return None
        return buffer.raw

    def u32(va: int):
        data = read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    result = {"command": args.command, "pid": pid, "main_tid": tid, "status": "waiting"}
    payload_text = "\n" + args.command + "\n"
    payload = payload_text.encode("ascii") + b"\0"
    deadline = time.monotonic() + args.timeout
    try:
        if args.no_room_wait:
            room = u32(ROOM_POINTER)
        else:
            while time.monotonic() < deadline:
                room = u32(ROOM_POINTER)
                if room and u32(room + 0x278) is not None and u32(room + 0x278) & 0xFF == 1:
                    break
                time.sleep(0.2)
            else:
                result["status"] = "room_not_ready"
                print(json.dumps(result, ensure_ascii=False))
                return 2
        if k32.SuspendThread(thread) == 0xFFFFFFFF:
            result.update(status="suspend_failed", error=C.get_last_error())
            print(json.dumps(result, ensure_ascii=False))
            return 3
        try:
            descriptor = read(DESCRIPTOR, 12)
            pointer, capacity, length = struct.unpack("<3I", descriptor)
            if pointer != BUFFER_POINTER or capacity != BUFFER_CAPACITY:
                result.update(status="descriptor_mismatch", pointer=hex(pointer), capacity=capacity)
                return 4
            if length + len(payload) > capacity:
                result.update(status="buffer_full", length=length)
                return 5
            lock = struct.unpack("<4I", read(LOCK, 16))
            result.update(lock_recursion=lock[2], lock_owner=hex(lock[3]))
            wrote = C.c_size_t()
            if not k32.WriteProcessMemory(handle, C.c_void_p(pointer + length),
                                          C.create_string_buffer(payload, len(payload)),
                                          len(payload), C.byref(wrote)) or wrote.value != len(payload):
                result.update(status="payload_write_failed", error=C.get_last_error())
                return 6
            new_length = length + len(payload_text)
            if not k32.WriteProcessMemory(handle, C.c_void_p(DESCRIPTOR + 8),
                                          C.create_string_buffer(struct.pack("<I", new_length), 4),
                                          4, C.byref(wrote)) or wrote.value != 4:
                result.update(status="length_write_failed", error=C.get_last_error())
                return 7
            result.update(status="queued", length_before=length, length_after=new_length,
                          room=hex(room), pointer=hex(pointer))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        finally:
            k32.ResumeThread(thread)
    finally:
        k32.CloseHandle(thread)
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
