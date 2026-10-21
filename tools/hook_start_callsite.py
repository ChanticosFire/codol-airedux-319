"""Record calls to the room start entry 0x62F840 (ecx, return address, count)."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
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

TARGET = 0x62F840
BACK = 0x62F848


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
    original = r(h, TARGET, 8)
    assert original.hex() == "558becb814200000", original.hex()
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    count = cave + 0x800
    ecx_save = cave + 0x804
    ret_save = cave + 0x808
    code = bytearray()
    code += b"\x89\x0d" + struct.pack("<I", ecx_save)       # mov [ecx_save],ecx
    code += b"\x8b\x04\x24"                                 # mov eax,[esp]
    code += b"\xa3" + struct.pack("<I", ret_save)           # mov [ret_save],eax
    code += b"\xff\x05" + struct.pack("<I", count)          # inc dword [count]
    code += original
    code += b"\xe9" + struct.pack("<i", BACK - (cave + len(code) + 5))
    w(h, cave, bytes(code))
    w(h, count, b"\x00" * 4)
    old = W.DWORD()
    if not k32.VirtualProtectEx(h, C.c_void_p(TARGET), 8, 0x40, C.byref(old)):
        raise OSError(f"protect: {C.get_last_error()}")
    w(h, TARGET, b"\xe9" + struct.pack("<i", cave - (TARGET + 5)) + b"\x90\x90\x90")
    k32.FlushInstructionCache(h, C.c_void_p(TARGET), 8)
    print(json.dumps({"pid": p, "cave": hex(cave), "count": hex(count),
                      "ecx_save": hex(ecx_save), "ret_save": hex(ret_save),
                      "original": original.hex()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
