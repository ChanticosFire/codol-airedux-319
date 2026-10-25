"""Watch the local player's position while injecting movement keys.

We found that zeroing three 0x01 bytes in the real baseline snapshot removes the
spectator hints and gives a ground-level first person view ("press space").
This script samples the clc position/velocity neighbourhood before and after
sending SPACE and W/S so we can prove whether the player actually moves.

Sampled window: clc+0x3C60 .. clc+0x3CA0 as floats, plus net/ui state.
"""
import ctypes
import struct
import sys
import time

from ctypes import wintypes as W

pid = int(sys.argv[1])
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

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


def f32(a):
    v = u32(a)
    if v is None:
        return None
    return struct.unpack("<f", struct.pack("<I", v))[0]


def snapshot(tag):
    net = u32(0x76446B0)
    ui = u32(0x84ABA50)
    enc = u32(0x76638F4)
    if not enc:
        print("  [%s] clc unreadable" % tag)
        return None
    clc = (enc ^ XOR) & 0xFFFFFFFF
    vals = [f32((clc + off) & 0xFFFFFFFF) for off in (0x3C80, 0x3C84, 0x3C88)]
    print("  [%-8s] net=%-3s ui=%-3s pos=(%.3f, %.3f, %.3f)" % (
        tag, net, ui, vals[0], vals[1], vals[2]))
    return tuple(vals)


print("  sampling baseline (no keys) ...")
samples = []
t0 = time.monotonic()
while time.monotonic() - t0 < seconds:
    s = snapshot("idle%02d" % len(samples))
    if s:
        samples.append(s)
    time.sleep(2.0)

print()
print("  === idle samples ===")
uniq = sorted(set(samples))
for u in uniq:
    print("    %.3f, %.3f, %.3f" % u)
print("  distinct idle positions:", len(uniq))
