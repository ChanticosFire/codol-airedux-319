"""Scan the clientConnection_t neighbourhood for the client's own slot number.

We know clc = [0x76638F4] ^ 0x6891D1C7 and clc+0x3BE4 is the "snapshot parsed"
flag (verified: it flips to 1 periodically).  Somewhere in this structure the
client stores which player slot is "me" (clientNum) and who it is spectating.

A spectator state means the client could not match a playerstate to its own
slot.  If clientNum is 0..18 we can find it by scanning for plausible values.
"""
import ctypes
import struct
import sys

from ctypes import wintypes as W

pid = int(sys.argv[1])
XOR = 0x6891D1C7

k = ctypes.WinDLL("kernel32")
k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(0x438, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")


def u32(a):
    b = ctypes.create_string_buffer(4)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, 4, ctypes.byref(g)):
        return None
    return struct.unpack("<I", b.raw)[0]


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        return None
    return b.raw


enc = u32(0x76638F4)
if not enc:
    raise SystemExit("cannot read encoded clc")
clc = (enc ^ XOR) & 0xFFFFFFFF
print("  encoded=[0x76638F4]=%#x   clc=%#x" % (enc, clc))
print("  clc+0x3BE4 (snapshot flag) =", u32((clc + 0x3BE4) & 0xFFFFFFFF))
print()

# Dump a window around the snapshot flag: the playerstate/bookkeeping lives nearby.
base_off = 0x3B80
size = 0x120
buf = rd((clc + base_off) & 0xFFFFFFFF, size)
if not buf:
    raise SystemExit("cannot read window")

print("=== words in clc+%#x .. clc+%#x ===" % (base_off, base_off + size))
for i in range(0, size, 4):
    v = struct.unpack_from("<I", buf, i)[0]
    off = base_off + i
    tag = ""
    if off == 0x3BE4:
        tag = "  <-- snapshot parsed flag"
    print("  +%#06x  %#010x  %12d%s" % (off, v, v if v < 0x80000000 else v - 0x100000000, tag))
