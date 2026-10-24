"""Sample net_state plus the loading-object fields, to see what breaks at CA_PRIMED.

Round 56 caught: net 1 -> 3 -> 4 -> 5 -> 8, chan=0x9D, table 0->1, then a crash
about 0.1 s after net reached 8.  This version adds the loading-object fields so
the last few samples before the crash show whether the loader had progressed.

Usage: python runs/_sample_state2.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 55.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 10.0) / 1000.0

NET_STATE = 0x76446B0
FLAG_C = 0x76446A3
ENC_CONN = 0x331C0C8
UI_STATE = 0x84ABA50
TABLE = 0x827F738
LOADING_OBJ = 0x8536F60
HOLDER = 0x8269774
LOAD_STATUS = 0x84ABA7C
STAGE = 0xE59D20
GATE = 0x1C2B6CC
KEY_XOR = 0xD362501F

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

h = k.OpenProcess(0x438, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")


def u32(addr):
    if not addr:
        return None
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0]


def u8(addr):
    buf = ctypes.create_string_buffer(1)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 1, ctypes.byref(got)):
        return None
    return buf.raw[0]


def snapshot():
    obj = u32(LOADING_OBJ) or 0
    holder = u32(HOLDER) or 0
    loader = (u32(holder + 0x4F4) or 0) if holder else 0
    return (
        u32(NET_STATE),
        u8(FLAG_C),
        obj,
        u32(obj + 0x14) if obj else None,          # loading object stage
        (u32(loader + 0x5E8) if loader else None),  # CA_LOADING marker
        u32(LOAD_STATUS),
        u32(UI_STATE),
        u32(TABLE),
        u32(GATE),
    )


t0 = time.monotonic()
prev = snapshot()
print(f"t+0.00 net={prev[0]} c={prev[1]} obj={hex(prev[2] or 0)} "
      f"obj14={prev[3]} L5E8={prev[4]} loadst={prev[5]} ui={prev[6]} "
      f"table={prev[7]} gate={prev[8]}", flush=True)

while time.monotonic() - t0 < SECONDS:
    cur = snapshot()
    if cur != prev:
        print(f"t+{time.monotonic() - t0:6.2f} net={cur[0]} c={cur[1]} "
              f"obj={hex(cur[2] or 0)} obj14={cur[3]} L5E8={cur[4]} "
              f"loadst={cur[5]} ui={cur[6]} table={cur[7]} gate={cur[8]}", flush=True)
        prev = cur
    time.sleep(INTERVAL)

print("sampling done", flush=True)
