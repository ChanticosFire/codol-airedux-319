"""Route D: build a derived-class instance by hand and call the begin-game
method on it.

Sections 909-911 established:
  * 0x62F840 (begin-game) is vtable slot 0 of 0xDC7750 and slot 0xF of 0xDC7274;
  * it reads [this+0x278], [this+0x105D8], [this+0x105FE], [this+0x106F8];
  * the base constructor at 0x62C000 only creates a ~0x120-byte object;
  * vtable 0xDC7750 has zero references - the derived class is never constructed.

So we manufacture one: allocate ~0x11000 bytes, store 0xDC7750 at offset 0,
leave the rest zero (the fields the method reads are flags and counters whose
natural default is 0), then call 0x62F840 with that pointer as `this`.

    python tools/derive_obj_1649370.py --pid N                 # build + call
    python tools/derive_obj_1649370.py --pid N --no-call       # build only
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

VTABLE = 0xDC7750
OBJ_SIZE = 0x11000
BEGIN_GAME = 0x62F840

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--size", type=lambda v: int(v, 0), default=OBJ_SIZE)
    ap.add_argument("--no-call", action="store_true")
    args = ap.parse_args()

    h = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    def write(va: int, blob: bytes) -> bool:
        old = W.DWORD()
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), 0x40, ctypes.byref(old))
        buf = ctypes.create_string_buffer(blob, len(blob))
        ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(blob),
                                    ctypes.byref(n))
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), old.value,
                             ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(va), len(blob))
        return bool(ok)

    obj = int(k32.VirtualAllocEx(h, None, args.size, 0x3000, 0x40) or 0)
    if not obj:
        raise SystemExit("VirtualAllocEx failed")

    if not write(obj, struct.pack("<I", VTABLE)):
        raise SystemExit("failed to write vtable pointer")
    print(f"derived object at {obj:#x} size {args.size:#x} vtable {VTABLE:#x}")
    print(f"call: call_once_1649370.py --pid {args.pid} --fn {BEGIN_GAME:#x} "
          f"--ecx {obj:#x} --arg 0")
    if args.no_call:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
