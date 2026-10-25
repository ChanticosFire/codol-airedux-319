"""Poll net_state/table/gate and the fastfile-name collector, printing NEW names.

Round 74 hooked 0x49ED40 (FS_LoadFastfile) and polled only the call COUNT, so the
actual file names requested after gate=1 were never printed.  This poller tracks
the collected names incrementally and prints each new one with a timestamp, so
the last file requested before the crash is visible even though the process dies.

Usage: python runs/_poll_ff.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 40.0) / 1000.0

NET_STATE = 0x76446B0
TABLE = 0x827F738
GATE = 0x1C2B6CC
FF_COUNT = 0xE54E000
FF_BASE = 0xE54E100
FF_STRIDE = 64
MAX_NAMES = 64

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


def name_at(i):
    buf = ctypes.create_string_buffer(FF_STRIDE)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(FF_BASE + i * FF_STRIDE),
                               buf, FF_STRIDE, ctypes.byref(got)):
        return None
    z = buf.raw.find(b"\x00")
    raw = buf.raw[:z] if z >= 0 else buf.raw
    return raw.decode("ascii", "replace")


t0 = time.monotonic()
seen = []
last_meta = None
gone = False
while time.monotonic() - t0 < SECONDS:
    net = u32(NET_STATE)
    table = u32(TABLE)
    gate = u32(GATE)
    cnt = u32(FF_COUNT)
    meta = (net, table, gate, cnt)
    ts = time.monotonic() - t0
    if meta != last_meta:
        print(f"t+{ts:6.2f} net={net} table={table} gate={gate} ff_count={cnt}", flush=True)
        last_meta = meta
    if cnt:
        for i in range(len(seen), min(cnt, MAX_NAMES)):
            nm = name_at(i)
            if nm:
                print(f"t+{ts:6.2f}   NEW ff[#{i}] = {nm}", flush=True)
                seen.append(nm)
            else:
                break
    if net is None:
        gone = True
        print(f"t+{ts:6.2f} CLIENT GONE", flush=True)
        break
    time.sleep(INTERVAL)

print(f"gone={gone} total_names={len(seen)}", flush=True)
for i, nm in enumerate(seen):
    print(f"  [{i:2d}] {nm}", flush=True)
