"""Resolve a vtable address to a class name via MSVC RTTI.

For an object whose vtable lives at 0xD5B12C, the vtable's -4 slot points at a
RTTI Complete Object Locator, which in turn names the class. This walks that
chain in the live process and prints whatever it finds.

    python tools/rtti_name.py 0xD5B12C
    python tools/rtti_name.py 0xD5B12C --pid 1234
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def u32(h, va: int):
    d = read(h, va, 4)
    return struct.unpack("<I", d)[0] if len(d) == 4 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vtable")
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()

    vtable = int(args.vtable, 16)
    pid = args.pid or find_pid()
    if not pid:
        print("client not running and no --pid given")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    print(f"pid={pid} vtable={vtable:#x}")
    try:
        # MSVC: the dword before the vtable points at the Complete Object Locator
        col = u32(h, vtable - 4)
        print(f"COL @ vtable-4 = {col:#x}" if col else "COL unreadable")
        if not col:
            return 4
        # COL: signature, offset, cdOffset, pTypeDescriptor, pClassDescriptor
        raw = read(h, col, 24)
        if len(raw) < 24:
            print("COL too short")
            return 5
        sig, offset, cd = struct.unpack_from("<III", raw, 0)
        td, cd_ptr = struct.unpack_from("<II", raw, 12)
        print(f"  signature   {sig:#x} ({'x64' if sig == 1 else 'expected 0'})")
        print(f"  offset      {offset:#x}")
        print(f"  type_desc   {td:#x}")
        print(f"  class_desc  {cd_ptr:#x}")
        # TypeDescriptor: vtable ptr, spare, then a mangled name
        if td:
            head = read(h, td, 16)
            name = read(h, td + 16, 256)
            end = name.find(b"\x00")
            if end > 0:
                name = name[:end]
            print(f"  mangled     {name.decode('latin1', 'replace')}")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
