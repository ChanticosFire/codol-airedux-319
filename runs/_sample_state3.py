"""Sample net_state and the loading object REAL fields (fixed version).

The previous sampler treated 0x8536F60 as a pointer-to-object and dereferenced
it, so it always reported obj=0 / obj14=None.  Round 65/66 established that
0x8536F60 IS the object (a __thiscall `this`), so fields must be read as
`0x8536F60 + offset` directly.

Usage: python runs/_sample_state3.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 5.0) / 1000.0

NET_STATE = 0x76446B0
ENC_CONN = 0x331C0C8
UI_STATE = 0x84ABA50
TABLE = 0x827F738
GATE = 0x1C2B6CC
OBJ = 0x8536F60          # the object itself, NOT a pointer
LOAD_STATUS = 0x84ABA7C
KEY_XOR = 0xD362501F
OBJ_FIELDS = (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C)

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

h = k.OpenProcess(0x438, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")


def u32(addr):
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0]


def snapshot():
    fields = tuple(u32(OBJ + off) for off in OBJ_FIELDS)
    enc = u32(ENC_CONN)
    conn = (enc ^ KEY_XOR) if enc else 0
    chan = u32(conn + 0x28) if 0x10000 <= (conn or 0) < 0x7FFF0000 else None
    return (u32(NET_STATE), chan, u32(UI_STATE), u32(TABLE), u32(GATE),
            u32(LOAD_STATUS), fields)


def fmt(s):
    net, chan, ui, table, gate, loadst, fields = s
    fs = " ".join("--" if v is None else f"{v:08x}" for v in fields)
    return (f"net={net} chan={chan} ui={ui} table={table} gate={gate} "
            f"loadst={loadst} obj[{fs}]")


t0 = time.monotonic()
prev = snapshot()
print(f"t+0.00 {fmt(prev)}", flush=True)

while time.monotonic() - t0 < SECONDS:
    cur = snapshot()
    if cur != prev:
        print(f"t+{time.monotonic() - t0:6.2f} {fmt(cur)}", flush=True)
        prev = cur
    time.sleep(INTERVAL)

print("sampling done", flush=True)
