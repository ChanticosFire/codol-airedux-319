"""Hook the 0x945CE0 container lookup and record its 'this' and return address."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import sys
import time
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]

TARGET = 0x945CE0
BACK = 0x945CE6


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) > 1 and p[1].isdigit():
            return int(p[1])
    raise SystemExit("client not running")


def w(h, a, data):
    g = C.c_size_t()
    if not k32.WriteProcessMemory(h, C.c_void_p(a), C.create_string_buffer(data, len(data)),
                                  len(data), C.byref(g)) or g.value != len(data):
        raise OSError(f"write {a:#x}: {C.get_last_error()}")


def r(h, a, n):
    b = C.create_string_buffer(n)
    g = C.c_size_t()
    if not k32.ReadProcessMemory(h, C.c_void_p(a), b, n, C.byref(g)) or g.value != n:
        raise OSError(f"read {a:#x}: {C.get_last_error()}")
    return b.raw


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    original = r(h, TARGET, 6)
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    save_ecx = cave + 0x800
    save_ret = cave + 0x804
    code = bytearray()
    code += b"\x89\x0d" + struct.pack("<I", save_ecx)   # mov [ecx],ecx
    code += b"\x8b\x04\x24"                             # mov eax,[esp] (return address)
    code += b"\xa3" + struct.pack("<I", save_ret)       # mov [ret],eax
    code += original
    code += b"\xe9" + struct.pack("<i", BACK - (cave + len(code) + 5))
    w(h, cave, bytes(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(h, C.c_void_p(TARGET), 6, 0x40, C.byref(old)):
        raise OSError(f"protect: {C.get_last_error()}")
    patch = b"\xe9" + struct.pack("<i", cave - (TARGET + 5)) + b"\x90"
    w(h, TARGET, patch)
    k32.FlushInstructionCache(h, C.c_void_p(TARGET), 6)
    print(json.dumps({"pid": p, "cave": hex(cave), "ecx_save": hex(save_ecx),
                      "ret_save": hex(save_ret), "original": original.hex()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
