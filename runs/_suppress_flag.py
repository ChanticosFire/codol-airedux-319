"""Keep clearing 0xC7341DB for the whole handshake window.

Round 46 showed the client restores this flag to 1 within ~45 s of us clearing
it, which makes 0x5BF3E0 skip the connection-identity init and leaves the six
`[conn+0x109260..0x109274]` keys at zero.  A single write is therefore not
enough -- suppress it continuously.

Usage: python runs/_suppress_flag.py <pid> [seconds] [interval_ms]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
INTERVAL = (float(sys.argv[3]) if len(sys.argv) > 3 else 20.0) / 1000.0

FLAG = 0xC7341DB
KEYS = (0x109260, 0x109264, 0x109268, 0x10926C, 0x109270, 0x109274)

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.VirtualProtectEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                               W.DWORD, ctypes.POINTER(W.DWORD)]
k.VirtualProtectEx.restype = W.BOOL

h = k.OpenProcess(0x1F0FFF, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")

old = W.DWORD()
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, 0x40, ctypes.byref(old))
one = ctypes.create_string_buffer(b"\x00", 1)


def u32(addr):
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0]


deadline = time.monotonic() + SECONDS
cleared = 0
next_report = time.monotonic() + 5.0
last_keys = None
try:
    while time.monotonic() < deadline:
        got = ctypes.c_size_t()
        if k.WriteProcessMemory(h, ctypes.c_void_p(FLAG), one, 1, ctypes.byref(got)):
            cleared += 1
        now = time.monotonic()
        if now >= next_report:
            enc = u32(0x331C0C8)
            conn = (enc ^ 0xD362501F) if enc else 0
            keys = [u32(conn + off) for off in KEYS] if 0x10000 <= conn < 0x7FFF0000 else None
            net = u32(0x76446B0)
            table = u32(0x827F738)
            print(f"t+{SECONDS - (deadline - now):5.1f}s writes={cleared:5d} "
                  f"net={net} table={table} keys={keys}", flush=True)
            if keys and any(keys):
                last_keys = keys
        time.sleep(INTERVAL)
finally:
    k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, old.value, ctypes.byref(old))

print(f"done: {cleared} clears")
if last_keys:
    print(f"non-zero keys observed: {[hex(x or 0) for x in last_keys]}")
