"""Scan the live room object for map names and inspect the 0x33069D4 playlist."""
from __future__ import annotations

import ctypes as C
import re
import struct
import subprocess
import sys
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) > 1 and p[1].isdigit():
            return int(p[1])
    raise SystemExit("client not running")


def rd(h, a, n):
    b = C.create_string_buffer(n)
    g = C.c_size_t()
    if not k32.ReadProcessMemory(h, C.c_void_p(a), b, n, C.byref(g)):
        return None
    return b.raw


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    room = struct.unpack("<I", rd(h, 0x82E13FC, 4))[0]
    print("room", hex(room))
    data = rd(h, room, 0x40000)
    if data:
        for m in re.finditer(rb"[ -~]{5,}", data):
            s = m.group().decode("ascii", "replace")
            if "mp_" in s or "map" in s.lower() or "room" in s.lower():
                print(hex(room + m.start()), s[:120])
    print("--- playlist 0x33069D4")
    for i in range(5):
        ptr = struct.unpack("<I", rd(h, 0x33069D4 + i * 4, 4))[0]
        print(i, hex(ptr))
        if ptr:
            rec = rd(h, ptr, 0x40)
            if rec:
                print("  rec", rec.hex())
                sp = struct.unpack("<I", rec[:4])[0]
                if sp:
                    print("  name", repr(rd(h, sp, 64)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
