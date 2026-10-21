"""Patch 0xBA3420 (conn reset) to return immediately, so c8=4 is not forced."""
from __future__ import annotations

import ctypes as C
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


p = pid()
h = k32.OpenProcess(0x1F0FFF, False, p)
site = 0xBA3420
oldp = W.DWORD()
k32.VirtualProtectEx(h, C.c_void_p(site), 1, 0x40, C.byref(oldp))
w = C.c_size_t()
k32.WriteProcessMemory(h, C.c_void_p(site), C.create_string_buffer(b"\xc3", 1), 1, C.byref(w))
k32.VirtualProtectEx(h, C.c_void_p(site), 1, oldp.value, C.byref(oldp))
k32.FlushInstructionCache(h, C.c_void_p(site), 1)
print(f"patched 0xBA3420 -> c3 on pid {p}")
