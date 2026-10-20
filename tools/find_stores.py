"""Find every store to a static, including register forms.

The earlier scan only matched `mov dword [addr], imm32` (C7 05 ...), which misses
the far more common `mov [addr], eax` (A3) and `mov [addr], ecx/edx/...` (89 /r
with a modrm mod=00 rm=101 displacement). This covers all of them so a state
machine's writes can be enumerated completely.

    python tools/find_stores.py 0xE59D20
    python tools/find_stores.py 0xE59D20 --wait 20
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
CHUNK = 0x100000


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def patterns(addr: int) -> list[tuple[str, bytes]]:
    a = struct.pack("<I", addr)
    out = [("mov [addr],imm32", b"\xc7\x05" + a),
           ("mov [addr],eax", b"\xa3" + a),
           ("mov [addr],imm8", b"\xc6\x05" + a)]
    # 89 /r  modrm 00 000 rrr -> 89 05+r*8 ; r=0 is covered above
    for reg, name in ((1, "ecx"), (2, "edx"), (3, "ebx"), (6, "esi"), (7, "edi")):
        out.append((f"mov [addr],{name}", bytes([0x89, 0x05 + reg * 8]) + a))
    # inc/dec/or/and/add dword [addr], reg (01 /r)
    for reg, name in ((1, "ecx"), (2, "edx"), (3, "ebx"), (6, "esi"), (7, "edi")):
        out.append((f"add [addr],{name}", bytes([0x01, 0x05 + reg * 8]) + a))
    for reg, name in ((1, "ecx"), (2, "edx"), (3, "ebx")):
        out.append((f"or [addr],{name}", bytes([0x09, 0x05 + reg * 8]) + a))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--wait", type=int, default=30)
    parser.add_argument("--start", default="0x400000")
    parser.add_argument("--end", default="0x10000000")
    args = parser.parse_args()

    target = int(args.address, 16)
    pats = patterns(target)
    pid = 0
    deadline = time.time() + args.wait
    while time.time() < deadline and not pid:
        pid = find_pid()
        if not pid:
            time.sleep(1.0)
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    print(f"pid={pid} scanning stores to {target:#x}")
    start = int(args.start, 16)
    end = int(args.end, 16)
    found = []
    try:
        base = start
        while base < end:
            data = read(h, base, CHUNK)
            if data:
                for name, pat in pats:
                    i = data.find(pat)
                    while i >= 0:
                        found.append((base + i, name))
                        i = data.find(pat, i + 1)
            base += CHUNK
    finally:
        k32.CloseHandle(h)
    for va, name in sorted(found):
        print(f"  {va:#010x}  {name}")
    print(f"total {len(found)} stores, {len(pats)} patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
