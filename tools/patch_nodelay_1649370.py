"""Make CODOL's connect state machine always take the send branch.

`0x5C05F0` runs every frame.  Its state-2 (timeout) branch is:

    0x5C0693  edx = [0xC7AF6A8]        ; now
    0x5C06A4  eax = edx - [conn+0x30]  ; elapsed since last attempt
    0x5C06B3  cmp eax, 0xBB8           ; 3000 ms
    0x5C06B8  jl  0x5C0F1B             ; not yet -> return

Because the client itself calls this every frame it rewrites `[conn+0x30]`
before an external write can take effect, so "set the timestamp to zero" always
loses the race.  Patching the `jl` into two nops removes the wait entirely, so
the elapsed-time check always falls through to the second jump table
(`net_state 3 -> 0x5C070E`) which builds `getchallenge 0 "<addr>"` and calls the
sender.

    python tools/patch_nodelay_1649370.py --probe
    python tools/patch_nodelay_1649370.py
    python tools/patch_nodelay_1649370.py --restore
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
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

SITE = 0x5C06B8
ORIGINAL = bytes.fromhex("7c61")     # jl 0x5C0F1B  (rel8 0x61)
PATCH = bytes.fromhex("9090")        # nop nop


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

    current = read(SITE, 2)
    report = {
        "pid": pid, "site": hex(SITE),
        "bytes_now": current.hex() if current else None,
        "is_original": current == ORIGINAL,
        "is_patched": current == PATCH,
    }
    if args.probe:
        print(json.dumps(report, indent=2))
        return 0

    blob = ORIGINAL if args.restore else PATCH
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(SITE), 2, 0x40, C.byref(old)):
        raise SystemExit("VirtualProtectEx failed")
    ok = write(SITE, blob)
    k32.VirtualProtectEx(handle, C.c_void_p(SITE), 2, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(SITE), 2)
    report.update(applied=ok, bytes_after=read(SITE, 2).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
