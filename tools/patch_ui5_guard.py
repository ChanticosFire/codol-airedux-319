"""Patch the `cmp eax, 2` guard so the load-screen state is never entered.

    0x7F2808  83 F8 02   cmp eax, 2
    0x7F280B  75 17      jne 0x7F2824

We rewrite the immediate to 0xFF so the comparison can never match, which keeps
0x7F2812 (`mov eax, 5` + `call 0x7F2580`) from ever running.  Must be applied
BEFORE the login state machine runs, otherwise ui_state is already 5 and the
state is self-locking.
"""
from __future__ import annotations

import argparse
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
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]

TARGET = 0x7F2808
ORIGINAL = bytes.fromhex("83f802")   # cmp eax, 2
PATCHED = bytes.fromhex("83f8ff")    # cmp eax, -1  (never equal for 0..4)


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(address: int, size: int) -> bytes:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return b""
        return buf.raw[:got.value]

    blob = PATCHED if args.restore else PATCHED
    want = ORIGINAL if args.restore else PATCHED
    current = read(TARGET, len(ORIGINAL))
    old_protect = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(TARGET), len(want), 0x40, C.byref(old_protect)):
        raise SystemExit("VirtualProtectEx failed")
    got = C.c_size_t()
    ok = k32.WriteProcessMemory(handle, C.c_void_p(TARGET),
                                C.create_string_buffer(want, len(want)), len(want), C.byref(got))
    k32.VirtualProtectEx(handle, C.c_void_p(TARGET), len(want), old_protect.value, C.byref(old_protect))
    print(json.dumps({"pid": pid, "address": hex(TARGET), "before": current.hex(),
                      "after": read(TARGET, len(want)).hex(), "ok": bool(ok),
                      "mode": "restore" if args.restore else "patch"}, ensure_ascii=True, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
