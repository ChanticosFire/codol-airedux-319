"""Overwrite the demo map-name field inside the client connection object.

    python tools/poke_map_name.py --name mp_cross_fire

The connection pointer is stored encoded at 0x331C0C8 (xor 0xD362501F).  The
demo map name lives at connection+0x108394 as a plain char array, so writing it
before the map fastfiles load (about 17 s after cl_demo_play) should switch the
map.  This script also tries the neighbouring 0x108294 field for comparison.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

CONNECTION_ENCODED = 0x331C0C8
CONNECTION_XOR = 0xD362501F


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="mp_cross_fire")
    ap.add_argument("--offset", type=lambda v: int(v, 0), default=0x108394)
    args = ap.parse_args()
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int | None:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return None
        return struct.unpack("<I", buf.raw)[0]

    def read(address: int, size: int) -> bytes:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return b""
        return buf.raw[:got.value]

    encoded = u32(CONNECTION_ENCODED) or 0
    connection = encoded ^ CONNECTION_XOR
    address = connection + args.offset
    before = read(address, 64).split(b"\0")[0].decode("latin-1", "replace") if connection else ""
    blob = args.name.encode() + b"\0"
    got = C.c_size_t()
    ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
    after = read(address, 64).split(b"\0")[0].decode("latin-1", "replace")
    row = {"pid": find_pid(), "encoded": hex(encoded), "connection": hex(connection),
           "address": hex(address), "before": before, "after": after,
           "status": "ok" if ok and got.value == len(blob) else "write_failed"}
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0 if row["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
