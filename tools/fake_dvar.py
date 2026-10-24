"""Install a minimal fake g_gametype dvar so demo playback passes both checks.

    python tools/fake_dvar.py --name g_gametype --value war

The client reads `[dvar+0xC]` as the current string.  Real registration never
runs in the offline shell, so `[0x32AA908]` is zero and 0x43204F / 0x5A5AC3
dereference it.  This allocates a tiny dvar_t + strings inside the process and
points the global at it, which keeps the shipped code unmodified.
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
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p

DVAR_GLOBAL = 0x32AA908
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04


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
    ap.add_argument("--name", default="g_gametype")
    ap.add_argument("--value", default="war")
    args = ap.parse_args()
    handle = k32.OpenProcess(0x0438, False, find_pid())
    if not handle:
        raise SystemExit("OpenProcess failed")

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    def u32(address: int) -> int:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return 0
        return struct.unpack("<I", buf.raw)[0]

    block = k32.VirtualAllocEx(handle, None, 0x1000, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not block:
        raise SystemExit("VirtualAllocEx failed")
    base = int(block)
    name_addr = base + 0x100
    value_addr = base + 0x140
    dvar_addr = base
    before = u32(DVAR_GLOBAL)
    ok = (write(name_addr, args.name.encode() + b"\0")
          and write(value_addr, args.value.encode() + b"\0")
          and write(dvar_addr, struct.pack("<IIII", name_addr, 0, 0, value_addr))
          and write(DVAR_GLOBAL, struct.pack("<I", dvar_addr)))
    row = {"pid": find_pid(), "dvar": hex(dvar_addr), "name": hex(name_addr),
           "value": hex(value_addr), "before": hex(before), "after": hex(u32(DVAR_GLOBAL)),
           "status": "ok" if ok else "write_failed"}
    print(json.dumps(row, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
