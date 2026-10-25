"""Find clc.state and the real vieworg.

Round 228 proved clc+0x3C80 is a constant, so it is not the view origin.
We also still do not know clc.state (CA_ACTIVE == 6 in COD4).

Strategy:
  1. dump clc+0x00 .. clc+0x80 (state lives at the very start of
     clientConnection_t: state, clientNum? , connectTime ...)
  2. scan a wide window for triples of plausible floats (finite, |v| < 20000)
     that look like a world position, and record them so we can diff later
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
    raise SystemExit("clc unreadable")
clc = (enc ^ XOR) & 0xFFFFFFFF
print("  clc = %#x   net=%s  ui=%s" % (clc, u32(0x76446B0), u32(0x84ABA50)))

print()
print("=== clc+0x00 .. clc+0x80 ===")
head = rd(clc, 0x80)
for i in range(0, 0x80, 4):
    v = struct.unpack_from("<I", head, i)[0]
    sv = v - 0x100000000 if v >= 0x80000000 else v
    f = struct.unpack_from("<f", head, i)[0]
    fs = ("%.3f" % f) if abs(f) < 1e6 and f == f else "-"
    print("  +%#04x  %#010x  %12d  float=%s" % (i, v, sv, fs))

print()
print("=== candidate position triples in clc+0x3000..clc+0x4000 ===")
# sample the playerstate neighbourhood; look for three consecutive plausible floats
lo, hi = 0x3000, 0x4000
buf = rd((clc + lo) & 0xFFFFFFFF, hi - lo)
if buf:
    found = []
    for i in range(0, len(buf) - 12, 4):
        vals = struct.unpack_from("<3f", buf, i)
        ok = all(v == v and abs(v) < 20000.0 for v in vals)
        if not ok:
            continue
        # a world position usually has at least one value with a fractional part
        # and is not all zeros
        if all(v == 0.0 for v in vals):
            continue
        nonint = sum(1 for v in vals if abs(v - round(v)) > 1e-4)
        if nonint >= 1 and abs(vals[0]) > 1.0:
            found.append((lo + i, vals))
    print("  found %d candidate triples" % len(found))
    for off, vals in found[:24]:
        print("    clc+%#06x  (%.3f, %.3f, %.3f)" % (off, vals[0], vals[1], vals[2]))
