"""Fine-grained sampler over the whole first 0x40 bytes of the loading object.

Round 69 showed the object's [+0x04] gets reallocated (2460c630 -> 4b3e6508)
right before the crash, so the interesting writes may land in fields beyond the
first 8 dwords.  This version samples 16 dwords at 1 ms and prints every change,
so the last field written before the crash is visible.

Usage: python runs/_sample_state4.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 1.0) / 1000.0

NET_STATE = 0x76446B0
UI_STATE = 0x84ABA50
TABLE = 0x827F738
GATE = 0x1C2B6CC
OBJ = 0x8536F60
ENC_CONN = 0x331C0C8
KEY_XOR = 0xD362501F
N_FIELDS = 16

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

h = k.OpenProcess(0x438, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")

BUF = ctypes.create_string_buffer(N_FIELDS * 4)
GOT = ctypes.c_size_t()


def block():
    if not k.ReadProcessMemory(h, ctypes.c_void_p(OBJ), BUF, N_FIELDS * 4, ctypes.byref(GOT)):
        return None
    return struct.unpack_from("<" + "I" * N_FIELDS, BUF.raw, 0)


def u32(addr):
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0]


def short(fields):
    if fields is None:
        return "obj=<gone>"
    return " ".join(f"{v:08x}" for v in fields)


t0 = time.monotonic()
prev_fields = block()
prev_meta = (u32(NET_STATE), u32(UI_STATE), u32(TABLE), u32(GATE))
print(f"t+0.00 net={prev_meta[0]} ui={prev_meta[1]} table={prev_meta[2]} "
      f"gate={prev_meta[3]}", flush=True)
print(f"        obj {short(prev_fields)}", flush=True)

while time.monotonic() - t0 < SECONDS:
    cur_fields = block()
    cur_meta = (u32(NET_STATE), u32(UI_STATE), u32(TABLE), u32(GATE))
    ts = time.monotonic() - t0
    if cur_meta != prev_meta:
        print(f"t+{ts:6.2f} net={cur_meta[0]} ui={cur_meta[1]} table={cur_meta[2]} "
              f"gate={cur_meta[3]}", flush=True)
        prev_meta = cur_meta
    if cur_fields != prev_fields:
        # report which indices changed
        if prev_fields is not None and cur_fields is not None:
            diff = [i for i in range(N_FIELDS) if cur_fields[i] != prev_fields[i]]
            d = ", ".join(f"+{i*4:#04x}:{prev_fields[i]:08x}->{cur_fields[i]:08x}"
                          for i in diff)
        else:
            d = "(object became unreadable or reappeared)"
        print(f"t+{ts:6.2f} obj {short(cur_fields)}   [{d}]", flush=True)
        prev_fields = cur_fields
    time.sleep(INTERVAL)

print("sampling done", flush=True)
