"""Locate the ui_mapname dvar by scanning, then point it at mp_crash_tropical.

`Dvar_FindVar` works but calling it from a helper process was unreliable here
(stdout encoding / timing).  The dvar is a static struct whose first field is a
pointer to the name string, so it can be found by scanning writable data for the
little-endian VA of "ui_mapname" (0xDB2F98).

Usage: python runs/_r243_scan.py <pid> [seconds]
"""
import ctypes
import struct
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
NAME_VA = 0xDB2F98          # pointer value stored in dvar+0x00 for "ui_mapname"


def read(addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return None
    return buf.raw


def u32(addr):
    d = read(addr, 4)
    return struct.unpack("<I", d)[0] if d else None


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
    d = read(addr, n)
    if not d:
        return None
    end = d.find(b"\x00")
    return d[:end] if 0 < end <= n else d


needle = struct.pack("<I", NAME_VA)
hits = []
for base in (0x7F000000, 0x80000000, 0x80100000, 0x80200000, 0x80300000,
             0x80400000, 0x80500000, 0x80600000, 0x80700000, 0x80800000,
             0x80900000, 0x80A00000, 0x80B00000, 0x80C00000, 0x80D00000):
    pass

# simpler: scan the client's own image/data range in 64 KiB chunks
CHUNK = 0x10000
start, end = 0x80000000, 0x82000000
addr = start
while addr < end and len(hits) < 8:
    blob = read(addr, CHUNK)
    if blob:
        pos = 0
        while True:
            i = blob.find(needle, pos)
            if i < 0:
                break
            hits.append(addr + i)
            pos = i + 1
    addr += CHUNK

print("scan candidates:", [hex(x) for x in hits])
dvar = None
for cand in hits:
    flags = u32(cand + 0x08) or 0
    value_ptr = u32(cand + 0x0C) or 0
    val = cstr(value_ptr) if 0x10000 <= value_ptr < 0x7FFF0000 else None
    print(f"  {cand:#010x} flags={flags:#06x} value_ptr={value_ptr:#010x} value={val!r}")
    if dvar is None and (flags & 0xFF) in (0x07, 0x06, 0x08):
        dvar = cand
    if dvar is None:
        dvar = cand

if dvar is None:
    raise SystemExit("ui_mapname dvar not found")

print()
print("using dvar =", hex(dvar))
print("state:", "ui=", u32(UI_STATE), "net=", u32(NET_STATE), "table=", u32(TABLE))

wbytes(STR_BUF, b"mp_crash_tropical\x00")
print("rewrite dvar+0x0C ->", w32(dvar + 0x0C, STR_BUF))
print("ui_mapname now =", cstr(u32(dvar + 0x0C) or 0))
print("table after write =", u32(TABLE))

for i in range(SAMPLE_SECONDS // 2):
    time.sleep(2)
    print(f"  t+{(i + 1) * 2:2d}s ui={u32(UI_STATE)} net={u32(NET_STATE)} "
          f"table={u32(TABLE)} stage={u32(STAGE)} "
          f"map={cstr(u32(dvar + 0x0C) or 0)}")
