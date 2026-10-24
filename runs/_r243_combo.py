"""Wait for net_state==5, then point ui_mapname at mp_crash_tropical and sample.

Two independently verified pieces are combined here:
  * `forward --start-challenge` + `patch_retry_ms` push the connection to
    net_state 5 (the CA_LOADING state where `table` drops to 0);
  * `Dvar_FindVar("ui_mapname")` + writing dvar+0x0C changes the UI map name
    even though the dvar is DVAR_ROM.

The write has to happen *while* net_state is 5: doing it while the client sits in
the connection-timeout dialog has no effect.

Usage: python runs/_r243_combo.py <pid> [seconds]
"""
import ctypes
import json
import re
import struct
import subprocess
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SAMPLE_SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 24

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

h = k.OpenProcess(0x1F0FFF, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")

STR_BUF = 0xC7AF590
UI_STATE = 0x84ABA50
NET_STATE = 0x76446B0
TABLE = 0x827F738
STAGE = 0xE59D20
LOADING_OBJ = 0x8536F60


def u32(addr):
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0]


def w32(addr, value):
    got = ctypes.c_size_t()
    return bool(k.WriteProcessMemory(h, ctypes.c_void_p(addr),
                                     ctypes.create_string_buffer(struct.pack("<I", value), 4),
                                     4, ctypes.byref(got)))


def wbytes(addr, blob):
    got = ctypes.c_size_t()
    return bool(k.WriteProcessMemory(h, ctypes.c_void_p(addr),
                                     ctypes.create_string_buffer(blob, len(blob)),
                                     len(blob), ctypes.byref(got)))


def cstr(addr, n=48):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return None
    raw = buf.raw
    end = raw.find(b"\x00")
    return raw[:end] if 0 < end <= n else raw


def find_dvar(name):
    wbytes(STR_BUF, name.encode() + b"\x00")
    proc = subprocess.run(
        [sys.executable, "tools/remote_call_1649370.py",
         "--target", "0x76F190", "--arg", hex(STR_BUF), "--pid", str(PID), "--settle", "1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    m = re.search(r'"result_eax":\s*"(0x[0-9a-fA-F]+)"', proc.stdout or "")
    if not m:
        print("  remote_call output:", (proc.stdout or "")[:300])
        return None
    return int(m.group(1), 16)


print("initial:", "ui=", u32(UI_STATE), "net=", u32(NET_STATE), "table=", u32(TABLE))

dvar = find_dvar("ui_mapname")
print("ui_mapname dvar =", hex(dvar) if dvar else None)
if not dvar:
    raise SystemExit("cannot locate ui_mapname dvar")
cur = u32(dvar + 0x0C) or 0
print("ui_mapname current value =", cstr(cur) if cur else None)
print("ui_mapname flags         =", hex(u32(dvar + 0x08) or 0))

print("waiting for net_state == 5 ...")
reached = None
deadline = time.monotonic() + 70
while time.monotonic() < deadline:
    if u32(NET_STATE) == 5:
        reached = time.monotonic()
        break
    time.sleep(0.05)

if reached is None:
    print("net_state never reached 5; last:", u32(NET_STATE), "table=", u32(TABLE))
    raise SystemExit(2)

print("net_state == 5 reached; table =", u32(TABLE))
wbytes(STR_BUF, b"mp_crash_tropical\x00")
print("rewrite ui_mapname +0x0C ->", w32(dvar + 0x0C, STR_BUF))
print("ui_mapname now =", cstr(u32(dvar + 0x0C) or 0))

for i in range(SAMPLE_SECONDS // 2):
    time.sleep(2)
    print(f"  t+{(i + 1) * 2:2d}s ui={u32(UI_STATE)} net={u32(NET_STATE)} "
          f"table={u32(TABLE)} stage={u32(STAGE)} "
          f"map={cstr(u32(dvar + 0x0C) or 0)}")
