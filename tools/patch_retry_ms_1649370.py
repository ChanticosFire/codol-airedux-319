"""Lower the connect retry delay from 3000 ms to 1 ms.

`patch_nodelay` replaced the whole `jl` with nops, which makes the state machine
build and send a `getchallenge` on *every* frame and destabilises the client.
This instead only changes the comparison constant:

    0x5C06B3  cmp eax, 0xBB8    ->   cmp eax, 0x00000001

so the elapsed-time test still exists (one attempt per frame at most) but is
satisfied almost immediately.

    python tools/patch_retry_ms_1649370.py --probe
    python tools/patch_retry_ms_1649370.py --ms 1
    python tools/patch_retry_ms_1649370.py --restore
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
k32.VirtualProtectEx.restype = W.BOOL
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]

SITE = 0x5C06B3
ORIGINAL = bytes.fromhex("3db80b0000")      # cmp eax, 0xbb8


def build(value: int) -> bytes:
    return b"\x3D" + struct.pack("<I", value)


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
    ap.add_argument("--ms", type=int, default=1)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, n: int) -> bytes | None:
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, n, C.byref(got)) or got.value != n:
            return None
        return buf.raw

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    current = read(SITE, 5)
    report = {
        "pid": pid, "site": hex(SITE),
        "bytes_now": current.hex() if current else None,
        "current_ms": struct.unpack("<I", current[1:5])[0] if current and current[0] == 0x3D else None,
        "is_original": current == ORIGINAL,
    }
    if args.probe:
        print(json.dumps(report, indent=2))
        return 0

    blob = ORIGINAL if args.restore else build(args.ms)
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(SITE), 5, 0x40, C.byref(old)):
        raise SystemExit("VirtualProtectEx failed")
    ok = write(SITE, blob)
    k32.VirtualProtectEx(handle, C.c_void_p(SITE), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(SITE), 5)
    report.update(applied=ok, bytes_after=read(SITE, 5).hex(),
                  mode="restore" if args.restore else f"ms={args.ms}")
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
