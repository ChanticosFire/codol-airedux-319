"""Read map/world state globals from the live client."""
from __future__ import annotations

import ctypes as C
import struct
import subprocess
import sys
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

# 0x3306910 is the command parser nesting index (idle -1), NOT a map index.
# 0x35053DC is the Com_Error reentrancy counter, NOT a world state.
# Keep these for context only, not as G2 world-loaded signals.
ADDRS = [0x35053DC, 0x766A20C, 0x7886BBC, 0x3306910, 0x337EAC0, 0x337EAC8,
         0x33E9990, 0x3306994, 0x76661A8, 0x76661AC, 0x76595A4, 0x76595A8, 0x76595AC]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) > 1 and p[1].isdigit():
            return int(p[1])
    raise SystemExit("client not running")


def read(h, va, n):
    b = C.create_string_buffer(n)
    g = C.c_size_t()
    if not k32.ReadProcessMemory(h, C.c_void_p(va), b, n, C.byref(g)):
        return None
    return b.raw


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    for a in ADDRS:
        b = read(h, a, 4)
        print(f"{a:08x} = {struct.unpack('<I', b)[0]:08x}" if b else f"{a:08x} = ?")
    for a, n in [(0x33821B0, 64), (0x337EAC0, 4)]:
        b = read(h, a, n)
        if b:
            print(f"{a:08x} bytes: {b!r}")
    ptr = read(h, 0x337EAC0, 4)
    if ptr:
        sptr = struct.unpack("<I", ptr)[0]
        s = read(h, sptr, 64) if sptr else None
        print("mapstr ptr", hex(sptr), repr(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())

