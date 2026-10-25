"""Verify the GetKeyboardState hook: toggle forced-W and diff cl.

Stub/cfg addresses come from runs/_hook_gks2.py output.  With cfg[0x57]=0x00 the
game sees no keys; with 0x80 it sees W held.  If forwardmove is real, some
4-byte slot must go 0 -> 127 (or similar) between the two states.
"""
import ctypes
import struct
import sys
import time

from ctypes import wintypes as W

pid = int(sys.argv[1])
CFG = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x41C80000
LO, HI = 0x0, 0xA000
XOR = 0x6891D1C7

k = ctypes.WinDLL("kernel32")
k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(0x1F0FFF, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        return None
    return b.raw


def wr(a, data):
    g = ctypes.c_size_t()
    buf = ctypes.create_string_buffer(data, len(data))
    return bool(k.WriteProcessMemory(h, ctypes.c_void_p(a), buf, len(data), ctypes.byref(g)))


def u32(a):
    b = rd(a, 4)
    return struct.unpack("<I", b)[0] if b else None


def set_forced(vk, val):
    return wr(CFG + vk, bytes([val]))


enc = u32(0x76638F4)
cl = (enc ^ XOR) & 0xFFFFFFFF
print("  cl=%#x  state=%s" % (cl, u32(0x76446B0)))

size = HI - LO

print("  cfg[0x57]=0  (no keys) ...")
set_forced(0x57, 0x00)
time.sleep(1.2)
a = rd(cl + LO, size)
print("  cfg[0x57]=0x80 (W held) ...")
set_forced(0x57, 0x80)
time.sleep(1.2)
b = rd(cl + LO, size)

if not (a and b):
    raise SystemExit("read failed")

print()
print("  === slots that changed 0 -> nonzero ===")
hits = []
for off in range(0, size - 4, 4):
    va = struct.unpack_from("<i", a, off)[0]
    vb = struct.unpack_from("<i", b, off)[0]
    if va == 0 and vb != 0 and abs(vb) <= 0x1000:
        hits.append((LO + off, vb))
for off, v in hits[:30]:
    print("    cl+%#06x = %d" % (off, v))
print("  total:", len(hits))

print()
print("  === slots that changed at all (small magnitudes) ===")
chg = []
for off in range(0, size - 4, 4):
    va = struct.unpack_from("<i", a, off)[0]
    vb = struct.unpack_from("<i", b, off)[0]
    if va != vb and abs(va) <= 0x10000 and abs(vb) <= 0x10000:
        chg.append((LO + off, va, vb))
for off, va, vb in chg[:24]:
    print("    cl+%#06x  %d -> %d" % (off, va, vb))
print("  total changed:", len(chg))

# leave W forced so screenshots show movement
print()
print("  (W remains forced; cfg[0x57]=0x80)")
