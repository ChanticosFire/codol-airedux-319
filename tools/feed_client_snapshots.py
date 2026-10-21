"""Feed synthetic svc_snapshot messages into the client ring after the gamestate.

The captured gamestate is the decoded server message (serverId 0 + svc_gamestate).
Each synthetic snapshot is the same 5-byte minimal message: serverId 0 + svc_snapshot.
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
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client process not found")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gamestate", type=Path)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return 0
        return struct.unpack("<I", buf.raw)[0]

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline and (u32(0xE59D20) or 0) < 4:
        time.sleep(0.5)
    time.sleep(2)
    gamestate = args.gamestate.read_bytes()
    payloads = [gamestate] + [b"\0\0\0\0\x06"] * args.count
    connection = (u32(0x331C0C8) ^ 0xD362501F)
    adr = struct.pack("<I4sHHIII", 4, b"\x7f\x00\x00\x01", socket.htons(28969), 0, 0, 0, 0x9D)
    wrote = C.c_size_t()
    if connection and 0x10000 <= connection < 0x7FFF0000:
        k32.WriteProcessMemory(handle, C.c_void_p(connection + 0x14),
                               C.create_string_buffer(adr, len(adr)), len(adr), C.byref(wrote))
    queued = 0
    for payload in payloads:
        for _ in range(50):
            cursor = u32(0x7872C04)
            read = u32(0x7872C00)
            if cursor - read < 14:
                slot = 0x786DBC0 + (cursor & 0xF) * 0x504
                for address, blob in ((slot, adr), (slot + 0x18, payload),
                                      (slot + 0x500, struct.pack("<I", len(payload)))):
                    k32.WriteProcessMemory(handle, C.c_void_p(address),
                                           C.create_string_buffer(blob, len(blob)), len(blob),
                                           C.byref(wrote))
                k32.WriteProcessMemory(handle, C.c_void_p(0x7872C04),
                                       C.create_string_buffer(struct.pack("<I", cursor + 1), 4), 4,
                                       C.byref(wrote))
                queued += 1
                break
            time.sleep(0.05)
        else:
            break
        time.sleep(args.interval)
    k32.WriteProcessMemory(handle, C.c_void_p(0x76446B0),
                           C.create_string_buffer(struct.pack("<I", 3), 4), 4, C.byref(wrote))
    print(json.dumps({"connection": hex(connection), "queued": queued,
                      "state": u32(0x76446B0), "cursor": u32(0x7872C04),
                      "read": u32(0x7872C00)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
