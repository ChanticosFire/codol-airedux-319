"""Scan playerState_t (starting at cl+0x3BA4) for the clientNum field.

We know pm_type == cl+0x3BA4 (verified: 2 -> 0 when the snapshot's spectator
bytes are zeroed).  COD4's playerState_t starts with pm_type/pm_flags/pm_time,
then viewangles, velocity, origin... and carries an int clientNum somewhere.

A clientNum must be a small integer in 0..18 (MAX_CLIENTS-1).  Scan the first
0x400 bytes of the struct and report every such slot, so we can tell which one
is stable across runs (the real clientNum) versus incidental small values.
"""
import ctypes
import struct
import sys

from ctypes import wintypes as W

pid = int(sys.argv[1])
XOR = 0x6891D1C7
BASE = 0x3BA4
SPAN = 0x400

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


enc = u32(0x76638F4)
if not enc:
    raise SystemExit("pointer unreadable")
cl = (enc ^ XOR) & 0xFFFFFFFF
print("  cl = %#x   cls.state=%s" % (cl, u32(0x76446B0)))
print("  playerState base = cl+%#x" % BASE)
print()

print("=== pm_type / pm_flags / pm_time ===")
for off in (BASE, BASE + 4, BASE + 8):
    print("  cl+%#06x = %s" % (off, u32((cl + off) & 0xFFFFFFFF)))

print()
print("=== slots holding 0..18 in the first %#x bytes of playerState ===" % SPAN)
hits = []
for off in range(0, SPAN, 4):
    v = u32((cl + BASE + off) & 0xFFFFFFFF)
    if v is None:
        break
    if 0 <= v <= 18:
        hits.append((off, v))
print("  %d candidate slots:" % len(hits))
for off, v in hits:
    print("    playerState+%#05x  (= cl+%#06x) = %d" % (off, BASE + off, v))

# Also show the first 32 dwords verbatim for structural eyeballing
print()
print("=== first 32 dwords of playerState ===")
for i in range(32):
    off = i * 4
    v = u32((cl + BASE + off) & 0xFFFFFFFF)
    if v is None:
        break
    f = struct.unpack("<f", struct.pack("<I", v))[0]
    fs = ("%.3f" % f) if abs(f) < 1e6 and f == f else "-"
    print("  +%#04x  %#010x  %10d  float=%s" % (off, v, v - 0x100000000 if v >= 0x80000000 else v, fs))
