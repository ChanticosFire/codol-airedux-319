"""Decisive test: write a DISTINCT origin and see whether it sticks.

Previous run re-wrote (336,60,261) which is also the value the client already
had, so we could not tell whether our writes took effect or were overwritten by
the same value.  Now we write (400, 120, 261) once and sample for a few seconds.

  - sticks   -> the client consumes our writes; movement is blocked elsewhere
  - reverts  -> the client rewrites playerState every frame; we must hook that
"""
import ctypes
import struct
import sys
import time

from ctypes import wintypes as W

pid = int(sys.argv[1])
XOR = 0x6891D1C7
PS = 0x3BA4

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


def f32(a):
    v = u32(a)
    return None if v is None else struct.unpack("<f", struct.pack("<I", v))[0]


def wf(a, v):
    b = struct.pack("<f", v)
    g = ctypes.c_size_t()
    return bool(k.WriteProcessMemory(h, ctypes.c_void_p(a), b, 4, ctypes.byref(g)))


enc = u32(0x76638F4)
cl = (enc ^ XOR) & 0xFFFFFFFF
base = (cl + PS) & 0xFFFFFFFF
print("  cl=%#x  playerState=%#x" % (cl, base))

xo, yo, zo = (base + 0xDC) & 0xFFFFFFFF, (base + 0xE0) & 0xFFFFFFFF, (base + 0xE4) & 0xFFFFFFFF


def show(tag):
    print("  [%-8s] origin=(%.2f, %.2f, %.2f)" % (tag, f32(xo), f32(yo), f32(zo)))


show("before")
print("  writing (400.0, 120.0, 261.0) ...")
print("   x ok=%s  y ok=%s  z ok=%s" % (wf(xo, 400.0), wf(yo, 120.0), wf(zo, 261.0)))
time.sleep(0.02)
show("+20ms")
for i in range(1, 6):
    time.sleep(0.4)
    show("+%.1fs" % (0.02 + i * 0.4))

print()
print("  === second attempt: write and immediately re-read 10x in a tight loop ===")
for i in range(10):
    wf(xo, 400.0)
    v = f32(xo)
    print("    iter %2d: wrote 400.0 -> read %.2f" % (i, v))
    time.sleep(0.02)
