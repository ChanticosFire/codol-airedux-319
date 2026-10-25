"""Identify the two dvars used by the timeout check at 0x5C265F.

    path A:  cmp [conn+0x34], [[0x33D64A0]+0xC]
    path B:  fld [[0x33395E0]+0xC] ; fmul [0xDE7B98]

If these are dvars, we can raise the limit without patching code.  Dvar layout
(established earlier): +0x00 name ptr, +0x08 flags, +0x0C value ptr.

Usage: python runs/_probe_timeout_dvars.py <pid>
"""
import ctypes
import struct
import sys
from ctypes import wintypes as W

PID = int(sys.argv[1])

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

h = k.OpenProcess(0x438, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")


def rd(addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return None
    return buf.raw


def u32(addr):
    d = rd(addr, 4)
    return struct.unpack("<I", d)[0] if d else None


def f32(addr):
    d = rd(addr, 4)
    return struct.unpack("<f", d)[0] if d else None


def f64(addr):
    d = rd(addr, 8)
    return struct.unpack("<d", d)[0] if d else None


def cstr(addr, n=64):
    if not addr or addr < 0x10000:
        return None
    d = rd(addr, n)
    if not d:
        return None
    z = d.find(b"\x00")
    return (d[:z] if z >= 0 else d).decode("latin-1", "replace")


print("=== conn ===")
enc = u32(0x331C0C8)
conn = (enc ^ 0xD362501F) if enc else 0
print(f"  enc={enc:#x} conn={conn:#x}")
if 0x10000 <= conn < 0x7FFF0000:
    print(f"  [conn+0x08] (start time)   = {u32(conn + 0x08)}")
    print(f"  [conn+0x0C] (start time 2) = {u32(conn + 0x0C)}")
    print(f"  [conn+0x30] (throttle ref) = {u32(conn + 0x30)}")
    print(f"  [conn+0x34] (retry count)  = {u32(conn + 0x34)}")

print()
print("=== dvar A: 0x33395E0 (used by the float path) ===")
pa = u32(0x33395E0)
print(f"  [0x33395E0] = {pa:#x}" if pa else "  [0x33395E0] = None")
if pa and 0x10000 <= pa < 0x7FFF0000:
    print(f"    name  = {cstr(u32(pa))}")
    print(f"    flags = {u32(pa + 8)}")
    vp = u32(pa + 12)
    print(f"    valueptr = {vp:#x}" if vp else "    valueptr = None")
    if vp:
        print(f"    int   = {u32(vp)}")
        print(f"    float = {f32(vp)}")

print()
print("=== dvar B: 0x33D64A0 (used by the retry-count path) ===")
pb = u32(0x33D64A0)
print(f"  [0x33D64A0] = {pb:#x}" if pb else "  [0x33D64A0] = None")
if pb and 0x10000 <= pb < 0x7FFF0000:
    print(f"    name  = {cstr(u32(pb))}")
    print(f"    flags = {u32(pb + 8)}")
    vp = u32(pb + 12)
    print(f"    valueptr = {vp:#x}" if vp else "    valueptr = None")
    if vp:
        print(f"    int   = {u32(vp)}")
        print(f"    float = {f32(vp)}")

print()
print("=== multiplier 0xDE7B98 (fmul operand, f64) ===")
print(f"  f64 = {f64(0xDE7B98)}")
print("  (if the dvar value is in seconds and this is 1/1000, result is ms)")
