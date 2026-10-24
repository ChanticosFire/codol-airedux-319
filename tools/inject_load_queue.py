"""Inject one fastfile name into the client's load queue.

    python tools/inject_load_queue.py --name common_gametype_mp [--pid N]

The engine drains ``[0x1D06440]`` (entries of 0x44 bytes, name at +0x00, flags at
+0x40) whenever ``[0x239B11C]`` is non-zero, calling 0x49ED40(name, flags) from its
own load loop.  Writing one entry therefore makes the client load the package on
its own thread with the correct context -- no code is executed by this tool.
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
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

QUEUE = 0x1D06440
COUNT = 0x239B11C
ENTRY_SIZE = 0x44
NAME_OFF, FLAGS_OFF = 0x00, 0x40


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
    ap.add_argument("--name", default="common_gametype_mp")
    ap.add_argument("--flags", type=lambda v: int(v, 0), default=1)
    ap.add_argument("--pid", type=int, default=0)
    args = ap.parse_args()
    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    block = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x04) or 0)
    if not block:
        raise SystemExit("VirtualAllocEx failed")

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    def read_u32(address: int) -> int:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got))
        return struct.unpack("<I", buf.raw)[0] if got.value == 4 else 0

    name_addr = block
    entry = bytearray(ENTRY_SIZE)
    struct.pack_into("<I", entry, NAME_OFF, name_addr)
    struct.pack_into("<I", entry, FLAGS_OFF, args.flags)

    before = read_u32(COUNT)
    # The engine passes the entry address itself to sprintf("%s.ff", name), so the
    # name must be INLINE at entry+0x00 (not a pointer).  flags live at +0x40.
    text = args.name.encode() + b"\0"
    if len(text) > FLAGS_OFF:
        raise SystemExit(f"name too long: {len(text)} > {FLAGS_OFF}")
    entry = bytearray(ENTRY_SIZE)
    entry[NAME_OFF:NAME_OFF + len(text)] = text
    struct.pack_into("<I", entry, FLAGS_OFF, args.flags)
    ok = write(QUEUE, bytes(entry)) and write(COUNT, struct.pack("<I", 1))
    print(json.dumps({"pid": pid, "name": args.name, "inline_bytes": len(text),
                      "queue_before": before, "written": ok}, ensure_ascii=True, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
