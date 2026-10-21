"""Hook the 0xBA4114 call to 0xC73900 and log its struct/return."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def w(h, a, data):
    g = C.c_size_t()
    k32.WriteProcessMemory(h, C.c_void_p(a), C.create_string_buffer(data, len(data)), len(data), C.byref(g))


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    log = cave + 0x400
    code = bytearray()
    for i in range(8):
        code += b"\x8b\x44\x24" + bytes([4 + i * 4])
        code += b"\xa3" + struct.pack("<I", log + i * 4)
    call_pos = len(code)
    code += b"\xe8\x00\x00\x00\x00"                 # call 0xC73900
    code += b"\xa3" + struct.pack("<I", log + 0x40) # mov [log+40],eax
    code += b"\xc3"
    struct.pack_into("<i", code, call_pos + 1, 0xC73900 - (cave + call_pos + 5))
    w(h, cave, bytes(code))
    # patch the call at 0xBA4114 (E8 rel32) to the cave
    site = 0xBA411A
    old = C.create_string_buffer(5)
    got = C.c_size_t()
    k32.ReadProcessMemory(h, C.c_void_p(site), old, 5, C.byref(got))
    oldp = W.DWORD()
    k32.VirtualProtectEx(h, C.c_void_p(site), 5, 0x40, C.byref(oldp))
    patch = b"\xe8" + struct.pack("<i", cave - (site + 5))
    w(h, site, patch)
    k32.VirtualProtectEx(h, C.c_void_p(site), 5, oldp.value, C.byref(oldp))
    k32.FlushInstructionCache(h, C.c_void_p(site), 5)
    Path("evidence/experiments/c73900-hook.json").write_text(json.dumps({
        "pid": p, "cave": hex(cave), "site": hex(site), "original_call": old.raw.hex(),
        "patch": patch.hex()}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pid": p, "cave": hex(cave), "site": hex(site)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
