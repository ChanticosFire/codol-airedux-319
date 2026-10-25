"""Point the client's master-server cvar at a host of our choosing.

Section 942/943 established that the master address lives in a plain QUAKE cvar
whose obfuscated name is "1860" (cvar object at [0x765E7C8], value pointer at
+0xC). Its current value is the hard-coded "cod4master.activision.com".

A QUAKE cvar object layout (observed at runtime):

    +0x00  char *name
    +0x04  int   flags
    +0x08  int   modification count
    +0x0C  char *string      <== current value
    +0x18  char *latched
    +0x24  char *reset

To change the value we write a new string into the client's memory and point
all three string fields at it, bumping the modification count so dependent
code notices the change.

    python tools/set_master_cvar_1649370.py --pid N --host 127.0.0.1:28969
    python tools/set_master_cvar_1649370.py --pid N --show
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

CVAR_GLOBAL = 0x765E7C8          # cvar "1860" object pointer
VAR_NAME = 0x00
VAR_FLAGS = 0x04
VAR_MOD = 0x08
VAR_STRING = 0x0C
VAR_LATCHED = 0x18
VAR_RESET = 0x24

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1:28969")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    h = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    def read(va: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, size, ctypes.byref(n))
        return buf.raw if ok and n.value == size else None

    def write(va: int, blob: bytes) -> bool:
        old = W.DWORD()
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), 0x40, ctypes.byref(old))
        buf = ctypes.create_string_buffer(blob, len(blob))
        ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(blob),
                                    ctypes.byref(n))
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), old.value,
                             ctypes.byref(old))
        return bool(ok)

    def u32(va: int) -> int | None:
        b = read(va, 4)
        return struct.unpack("<I", b)[0] if b else None

    cvar = u32(CVAR_GLOBAL)
    if not cvar:
        raise SystemExit("cvar 1860 pointer is null")
    name_ptr = u32(cvar + VAR_NAME)
    name = (read(name_ptr, 32) or b"").split(b"\x00")[0].decode("latin-1")
    val_ptr = u32(cvar + VAR_STRING)
    value = (read(val_ptr, 128) or b"").split(b"\x00")[0].decode("latin-1")
    print(f'cvar object {cvar:#x} name "{name}" value "{value}"')

    if args.show:
        return 0

    # allocate a fresh string inside the client
    blob = args.host.encode("latin-1") + b"\x00"
    mem = int(k32.VirtualAllocEx(h, None, 0x100, 0x3000, 0x40) or 0)
    if not mem:
        raise SystemExit("VirtualAllocEx failed")
    if not write(mem, blob):
        raise SystemExit("string write failed")

    # point all three string slots at the new buffer and bump the mod counter
    ok = True
    ok &= write(cvar + VAR_STRING, struct.pack("<I", mem))
    ok &= write(cvar + VAR_LATCHED, struct.pack("<I", mem))
    ok &= write(cvar + VAR_RESET, struct.pack("<I", mem))
    mod = u32(cvar + VAR_MOD) or 0
    ok &= write(cvar + VAR_MOD, struct.pack("<I", mod + 1))

    new_val = (read(u32(cvar + VAR_STRING), 128) or b"").split(b"\x00")[0]
    print(f'set to "{args.host}" -> {"ok" if ok else "FAILED"}, now "{new_val.decode("latin-1")}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
