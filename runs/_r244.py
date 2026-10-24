"""Point ui_mapname at mp_crash_tropical BEFORE the connection is established.

Round 18/19 established every piece:
  * the dvar is static at 0x80FC008 (verified across two independent launches);
  * it is DVAR_ROM (flags 0x107), so Dvar_SetString refuses, but writing the
    value pointer at +0x0C works;
  * 0xC7AF590 is a writable buffer that survives long enough to be read.

Doing the write before `forward --start-challenge` avoids the timing race that
made Round 19 fail (net_state had already fallen back to 0 by the time the write
ran).

Usage: python runs/_r244_pre.py <pid>
       python runs/_r244_sam.py <pid> [seconds]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
MODE = sys.argv[2] if len(sys.argv) > 2 else "pre"
SECONDS = int(sys.argv[3]) if len(sys.argv) > 3 else 20

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

DVAR = 0x80FC008            # ui_mapname, static (Round 18/19 verified)
NAME_VA = 0xDB2F98          # "ui_mapname"
STR_BUF = 0xC7AF590
UI_STATE = 0x84ABA50
NET_STATE = 0x76446B0
TABLE = 0x827F738
STAGE = 0xE59D20
LOADER = 0x8269774


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


def status():
    holder = u32(LOADER) or 0
    loader = (u32(holder + 0x4F4) or 0) if holder else 0
    c5e8 = u32(loader + 0x5E8) if loader else None
    return (f"ui={u32(UI_STATE)} net={u32(NET_STATE)} table={u32(TABLE)} "
            f"stage={u32(STAGE)} loader5E8={c5e8}")


if MODE == "pre":
    print("dvar name pointer =", hex(u32(DVAR) or 0), "(want 0xdb2f98)")
    if u32(DVAR) != NAME_VA:
        raise SystemExit("DVAR address assumption broken; aborting")
    print("flags =", hex(u32(DVAR + 8) or 0))
    print("value before =", cstr(u32(DVAR + 0xC) or 0))
    print("write map name ->", wbytes(STR_BUF, b"mp_crash_tropical\x00"))
    print("point dvar+0x0C ->", w32(DVAR + 0x0C, STR_BUF))
    print("value after  =", cstr(u32(DVAR + 0x0C) or 0))
    print("state:", status())
elif MODE == "check":
    print("value =", cstr(u32(DVAR + 0x0C) or 0), "| ", status())
else:
    for i in range(SECONDS // 2):
        time.sleep(2)
        print(f"  t+{(i + 1) * 2:2d}s {status()} map={cstr(u32(DVAR + 0x0C) or 0)}")
