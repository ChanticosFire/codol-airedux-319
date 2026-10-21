"""Read the 1649370 room fields used by the start path."""
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
    fields = [0xE360, 0x105D8, 0x105FC, 0x1061C, 0x1061D, 0x1061E,
              0x168, 0x16C, 0x170, 0x278, 0x280, 0x289]
    for off in fields:
        b = rd(h, room + off, 4)
        print(f"+{off:06x} = {struct.unpack('<I', b)[0]:08x}" if b else f"+{off:06x} = ?")
    for off, n in [(0x105F0, 0x40), (0x170, 0x80)]:
        b = rd(h, room + off, n)
        print(f"+{off:06x} bytes: {b.hex() if b else '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
