"""Force the 0xC73900 success branch at 0xBA4122 by NOPing the jne."""
from __future__ import annotations

import ctypes as C
import json
import subprocess
from ctypes import wintypes as W
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
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


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    site = 0xBA4122
    old = C.create_string_buffer(2)
    got = C.c_size_t()
    k32.ReadProcessMemory(h, C.c_void_p(site), old, 2, C.byref(got))
    oldp = W.DWORD()
    k32.VirtualProtectEx(h, C.c_void_p(site), 2, 0x40, C.byref(oldp))
    w = C.c_size_t()
    patch = b"\x90\x90"
    k32.WriteProcessMemory(h, C.c_void_p(site), C.create_string_buffer(patch, 2), 2, C.byref(w))
    k32.VirtualProtectEx(h, C.c_void_p(site), 2, oldp.value, C.byref(oldp))
    k32.FlushInstructionCache(h, C.c_void_p(site), 2)
    out = {"pid": p, "site": hex(site), "original": old.raw.hex(), "patch": patch.hex()}
    Path("evidence/experiments/c73900-success-patch.json").write_text(json.dumps(out, indent=2) + "\n",
                                                                      encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
