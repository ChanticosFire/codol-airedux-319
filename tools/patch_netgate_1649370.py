"""Force CODOL's network-gate check to pass, so the client will actually send.

`0x5BE700` is the gate that `0x5C05F0` consults on its state-0/3 branch:

    0x5BE700  eax = [0x7887040]              ; handle 1184
    0x5BE70F  call WaitForSingleObject(eax,0)
    0x5BE713  jne  fail                      ; not signaled -> return 0
    0x5BE715  eax = [0x7886E64]              ; handle 1180
    0x5BE71C  je   fail                      ; null -> return 0
    0x5BE721  call WaitForSingleObject(eax,0)
    0x5BE725  jne  fail                      ; not signaled -> return 0
    0x5BE727  mov al,1 / ret

In an offline/self-hosted environment those network-ready events are never
signalled, so the gate always fails and the client never transmits.

This patches the entry to `mov al,1; ret` (padded with nops):

    python tools/patch_netgate_1649370.py --probe
    python tools/patch_netgate_1649370.py
    python tools/patch_netgate_1649370.py --restore
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

GATE = 0x5BE700
ORIGINAL = bytes.fromhex("a1407078 08".replace(" ", ""))   # mov eax,[0x7887040]
PATCH = bytes.fromhex("b001c390")                          # mov al,1 ; ret ; nop
PATCH_LEN = len(PATCH)


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

    current = read(GATE, 6)
    report = {
        "pid": pid, "gate": hex(GATE),
        "bytes_now": current.hex() if current else None,
        "is_original": bool(current and current[:len(ORIGINAL)] == ORIGINAL),
        "is_patched": bool(current and current[:3] == PATCH[:3]),
    }
    if args.probe:
        print(json.dumps(report, indent=2))
        return 0

    blob = ORIGINAL if args.restore else PATCH
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(GATE), len(blob), 0x40, C.byref(old)):
        raise SystemExit(f"VirtualProtectEx failed err={C.get_last_error()}")
    ok = write(GATE, blob)
    k32.VirtualProtectEx(handle, C.c_void_p(GATE), len(blob), old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(GATE), len(blob))

    report.update(applied=ok, mode="restore" if args.restore else "patch",
                  bytes_after=read(GATE, 6).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
