"""Round 92 probe: is arg1 translated by Com_Error itself (0x4F2760), or pushed at 0x5C2589?

Also re-reads the patched bytes at 0x5C2530 to prove the NOP survived.

Usage: python runs/_probe_r307.py <pid> [seconds]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

SLOT_COMERR = 0xE551E00
SLOT_XLAT = 0xE551F00
PATCHED = 0x5C2530

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


def cstr(addr, n=96):
    if not addr or addr < 0x10000:
        return None
    d = rd(addr, n)
    if not d:
        return None
    z = d.find(b"\x00")
    return (d[:z] if z >= 0 else d).decode("latin-1", "replace")


t0 = time.monotonic()
last = None
while time.monotonic() - t0 < SECONDS:
    net = u32(0x76446B0)
    ce = u32(SLOT_COMERR) or 0
    xl = u32(SLOT_XLAT) or 0
    patched = rd(PATCHED, 2)
    key = (net, ce, xl, patched)
    if key != last:
        ts = time.monotonic() - t0
        ptxt = patched.hex(" ") if patched else "unreadable"
        line = f"t+{ts:5.2f} net={net} Com_Error={ce} xlat_0x4F2760={xl} bytes@0x5C2530={ptxt}"
        if ce:
            line += f"  arg1={u32(SLOT_COMERR + 12) or 0:#x} msg={cstr(u32(SLOT_COMERR+12) or 0)!r}"
        print(line, flush=True)
        last = key
    if net is None:
        print(f"t+{time.monotonic()-t0:5.2f} CLIENT GONE", flush=True)
        break
    time.sleep(0.07)

print("probe done", flush=True)
