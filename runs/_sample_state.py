"""Sample net_state and related connection fields to catch the reset to 0.

Static analysis found zero direct writes to 0x76446B0, so the reset has to be
observed at runtime.  This sampler records *transitions* (not every tick) so the
output stays readable, plus the netchan channel id which Round 1 established
should be 0x9D for a working connection.

Usage: python runs/_sample_state.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 20.0) / 1000.0

NET_STATE = 0x76446B0
FLAG_A = 0x76446A1
FLAG_B = 0x76446A4
FLAG_C = 0x76446A3
ENC_CONN = 0x331C0C8
UI_STATE = 0x84ABA50
TABLE = 0x827F738
KEY_XOR = 0xD362501F

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

h = k.OpenProcess(0x438, False, PID)   # read-only is enough
if not h:
    raise SystemExit("OpenProcess failed")


def u32(addr):
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
    enc = u32(ENC_CONN)
    conn = (enc ^ KEY_XOR) if enc else 0
    chan = u32(conn + 0x28) if 0x10000 <= conn < 0x7FFF0000 else None
    return (u32(NET_STATE), u8(FLAG_A), u8(FLAG_B), u8(FLAG_C), chan,
            u32(UI_STATE), u32(TABLE))


t0 = time.monotonic()
prev = snapshot()
print(f"t+0.00s  net={prev[0]} a={prev[1]} b={prev[2]} c={prev[3]} "
      f"chan={prev[4]} ui={prev[5]} table={prev[6]}", flush=True)

while time.monotonic() - t0 < SECONDS:
    cur = snapshot()
    if cur != prev:
        print(f"t+{time.monotonic() - t0:6.2f}s  net={cur[0]} a={cur[1]} b={cur[2]} "
              f"c={cur[3]} chan={cur[4]} ui={cur[5]} table={cur[6]}", flush=True)
        prev = cur
    time.sleep(INTERVAL)

print("sampling done", flush=True)
