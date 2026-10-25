"""Poll the last fastfile name handed to FS_LoadFastfile (0x49ED40).

Round 93 removed the timeout exit, so the client now proceeds to net=8, gate=1,
table=1 and dies with an unhandled exception ~0.14 s later.  Hooking 0x49ED40 and
tracking the most recent arg0 string tells us which resource was being loaded
when it died.

Usage: python runs/_poll_lastff.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 50.0) / 1000.0

SLOT = 0xE552100          # hook_any slot for 0x49ED40
NET_STATE = 0x76446B0
TABLE = 0x827F738
GATE = 0x1C2B6CC

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


def cstr(addr, n=80):
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
    net = u32(NET_STATE)
    cnt = u32(SLOT) or 0
    arg0 = u32(SLOT + 8) or 0
    table = u32(TABLE)
    gate = u32(GATE)
    key = (net, cnt, table, gate)
    if key != last:
        ts = time.monotonic() - t0
        line = f"t+{ts:5.2f} net={net} table={table} gate={gate} FS_Load calls={cnt}"
        if cnt:
            line += f"  last_ff={cstr(arg0)!r}"
        print(line, flush=True)
        last = key
    if net is None:
        print(f"t+{time.monotonic()-t0:5.2f} CLIENT GONE  (final FS_Load calls={cnt}, "
              f"last_ff={cstr(arg0)!r})", flush=True)
        break
    time.sleep(INTERVAL)

print("poll done", flush=True)
