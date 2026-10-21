"""Install a one-shot client-frame hook that calls the room start method at a safe frame boundary."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
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
k32.FlushInstructionCache.restype = W.BOOL

FRAME = 0x4FE220
FRAME_NEXT = 0x4FE22D
ROOM_GLOBAL = 0x82E13FC
START = 0x62F840


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
    original = r(h, FRAME, 13)
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    flag = cave + 0x800
    code = bytearray()
    code += b"\x60"                                  # pushad
    code += b"\x80\x3d" + struct.pack("<I", flag) + b"\x00"  # cmp byte [flag],0
    jne = len(code); code += b"\x75\x00"
    code += b"\xc6\x05" + struct.pack("<I", flag) + b"\x01"  # mov byte [flag],1
    mapstr = cave + 0x900
    code += b"\x68" + struct.pack("<I", mapstr)      # push map
    code += b"\x6a\x00"                              # push 0
    code += b"\x68" + struct.pack("<I", mapstr)      # push map
    call = len(code); code += b"\xe8\x00\x00\x00\x00"
    code += b"\x83\xc4\x0c"                          # add esp,0xc
    skip = len(code)
    code[jne + 1] = skip - (jne + 2)
    struct.pack_into("<i", code, call + 1, 0x4F3890 - (cave + call + 5))
    code += b"\x61"                                  # popad
    code += original
    jmp = len(code); code += b"\xe9\x00\x00\x00\x00"
    struct.pack_into("<i", code, jmp + 1, FRAME_NEXT - (cave + jmp + 5))
    w(h, cave, bytes(code))
    w(h, flag, b"\x00")
    w(h, cave + 0x900, b"mp_cross_fire\x00")
    old = W.DWORD()
    if not k32.VirtualProtectEx(h, C.c_void_p(FRAME), 13, 0x40, C.byref(old)):
        raise OSError(f"protect: {C.get_last_error()}")
    patch = b"\xe9" + struct.pack("<i", cave - (FRAME + 5)) + b"\x90\x90"
    w(h, FRAME, patch)
    k32.FlushInstructionCache(h, C.c_void_p(FRAME), 13)
    time.sleep(3)
    print(json.dumps({"pid": p, "cave": hex(cave), "flag": hex(flag), "original": original.hex(),
                      "code": bytes(code).hex()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


