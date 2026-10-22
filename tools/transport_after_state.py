"""Create the 1649370 game transport channel *after* the game state switches.

The launcher's automatic injector runs as soon as `connection` is valid (i.e.
while the frontend is still active) and the client exits.  This tool waits for
`[0x76446B0] == 3` (the game-state switch, see 20261022-gamestate-switch), then
pauses the window thread and runs `0x621E50(buf, adr, 2)` so the netadr and the
channel table are filled while the engine is in its game path.

    python tools/transport_after_state.py --port 8466
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import socket
import struct
import time
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
STATE = 0x76446B0
CONNECTION_ENCODED = 0x331C0C8
CONNECTION_XOR = 0xD362501F
HOST = 0xE85C68
CHANNEL_CREATE = 0x621E50

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
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.FlushInstructionCache.restype = W.BOOL
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenThread.restype = W.HANDLE
k32.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
k32.SetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
wow64_get.argtypes = [W.HANDLE, C.c_void_p]
wow64_set.argtypes = [W.HANDLE, C.c_void_p]

user32 = C.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8466)
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--wait", type=float, default=90)
    parser.add_argument("--call", type=lambda v: int(v, 0), default=CHANNEL_CREATE,
                        help="target function (default 0x621E50)")
    parser.add_argument("--ecx-connection", action="store_true",
                        help="set ECX=connection before the call (thiscall)")
    parser.add_argument("--set-state", action="store_true",
                        help="write state=3 first, then immediately create the channel")
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = k32.OpenProcess(0x0438, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(), "pid": pid}

    def read(va: int, count: int):
        buffer = C.create_string_buffer(count)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buffer, count,
                                     C.byref(got)) or got.value != count:
            return None
        return buffer.raw

    def u32(va: int):
        data = read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    def write(va: int, data: bytes) -> bool:
        wrote = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                           C.create_string_buffer(data, len(data)),
                                           len(data), C.byref(wrote))) \
            and wrote.value == len(data)

    try:
        if args.set_state:
            write(STATE, struct.pack("<I", 3))
            row["set_state"] = u32(STATE)
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline:
            if (u32(STATE) or 0) == 3:
                break
            time.sleep(0.5)
        row["state"] = u32(STATE)
        if row["state"] != 3:
            row["status"] = "state_not_3"
            return finish(row, args.output)
        encoded = u32(CONNECTION_ENCODED) or 0
        connection = encoded ^ CONNECTION_XOR
        row["connection"] = hex(connection)
        if not 0x10000 <= connection < 0x7FFF0000:
            row["status"] = "connection_invalid"
            return finish(row, args.output)
        host = u32(HOST) or 0
        biz = (u32(host + 0x1F0) or 0) if host else 0
        row.update(host=hex(host), biz=hex(biz),
                   gate_before=u32(biz + 0x18) if biz else None)
        if biz and u32(biz + 0x18) != 1:
            write(biz + 0x18, struct.pack("<I", 1))
            row["gate_after"] = u32(biz + 0x18)
        hwnd = user32.FindWindowW(args.window, None)
        if not hwnd:
            row["status"] = "no_window"
            return finish(row, args.output)
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        thread = k32.OpenThread(0x1F03FF, False, tid)
        cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40))
        if not cave:
            row["status"] = "alloc_failed"
            return finish(row, args.output)
        adr = connection + 0x14
        buf = cave + 0x100
        adr_bytes = struct.pack("<I4sHHIII", 4, b"\x7f\x00\x00\x01",
                                socket.htons(args.port), 0, 0, 0, 0x9D)
        if not write(adr, adr_bytes) or not write(buf, b"xx\x00"):
            row["status"] = "write_args_failed"
            return finish(row, args.output)
        if args.ecx_connection:
            code = b"\x60"
            code += b"\xb9" + struct.pack("<I", connection)
            code += b"\xe8" + struct.pack("<I", (args.call - (cave + len(code) + 5)) & 0xFFFFFFFF)
            code += b"\xa3" + struct.pack("<I", cave + 0x200)
            code += b"\x61\xc3"
        else:
            code = b"\x60\x6a\x02"
            code += b"\x68" + struct.pack("<I", buf)
            code += b"\x68" + struct.pack("<I", adr)
            code += b"\xe8" + struct.pack("<I", (args.call - (cave + len(code) + 5)) & 0xFFFFFFFF)
            code += b"\x83\xc4\x0c"
            code += b"\xa3" + struct.pack("<I", cave + 0x200)
            code += b"\x61\xc3"
        if not write(cave, code):
            row["status"] = "cave_write_failed"
            return finish(row, args.output)
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
        if k32.SuspendThread(thread) == 0xFFFFFFFF:
            row["status"] = "suspend_failed"
            return finish(row, args.output)
        try:
            context_size = 716
            eip_offset, esp_offset = 184, 196
            storage = C.create_string_buffer(context_size + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, context_size)
            C.c_uint32.from_address(aligned).value = 0x00010001
            if not wow64_get(thread, C.c_void_p(aligned)):
                row["status"] = "get_context_failed"
                return finish(row, args.output)
            original_eip = C.c_uint32.from_address(aligned + eip_offset).value
            original_esp = C.c_uint32.from_address(aligned + esp_offset).value
            write(original_esp - 4, struct.pack("<I", original_eip))
            C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
            C.c_uint32.from_address(aligned + eip_offset).value = cave
            if not wow64_set(thread, C.c_void_p(aligned)):
                row["status"] = "set_context_failed"
                return finish(row, args.output)
        finally:
            k32.ResumeThread(thread)
        time.sleep(0.5)
        row.update(status="called", ret=u32(cave + 0x200),
                   adr_after=read(adr, 16).hex() if read(adr, 16) else None,
                   channel=u32(connection + 0x28), t30=u32(connection + 0x30))
    finally:
        k32.CloseHandle(handle)
    return finish(row, args.output)


def finish(row: dict, output) -> int:
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
