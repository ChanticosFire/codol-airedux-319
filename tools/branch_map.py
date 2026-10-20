"""List every branch in a range with its target, to map control flow without guessing.

Earlier rounds tried to guess which single instruction guards a block. That failed repeatedly. This instead
dumps every branch in a span so the flow can be read directly: which jumps skip the block, and which land just
before it.

    python tools/branch_map.py --lo 0xBAE000 --hi 0xBAE460
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
JCC = ["o", "no", "b", "ae", "e", "ne", "be", "a",
       "s", "ns", "p", "np", "l", "ge", "le", "g"]


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lo", default="0xBAE000")
    ap.add_argument("--hi", default="0xBAE460")
    args = ap.parse_args()
    lo = int(args.lo, 0)
    hi = int(args.hi, 0)

    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 2
    try:
        code = read(h, lo, hi - lo)
        if not code:
            print("read failed")
            return 3
        print(f"branches in {lo:#x}..{hi:#x}")
        n = len(code)
        i = 0
        while i < n - 6:
            addr = lo + i
            b = code[i]
            if b == 0xE9:
                rel = struct.unpack_from("<i", code, i + 1)[0]
                print(f"  {addr:#08x}  jmp    -> {addr + 5 + rel:#08x}")
                i += 5
                continue
            if b == 0xEB:
                rel = struct.unpack_from("<b", code, i + 1)[0]
                print(f"  {addr:#08x}  jmp sh -> {addr + 2 + rel:#08x}")
                i += 2
                continue
            if b == 0x0F and i + 6 <= n and 0x80 <= code[i + 1] <= 0x8F:
                rel = struct.unpack_from("<i", code, i + 2)[0]
                cc = JCC[code[i + 1] - 0x80]
                print(f"  {addr:#08x}  j{cc:<5} -> {addr + 6 + rel:#08x}")
                i += 6
                continue
            if 0x70 <= b <= 0x7F:
                rel = struct.unpack_from("<b", code, i + 1)[0]
                cc = JCC[b - 0x70]
                print(f"  {addr:#08x}  j{cc:<5} -> {addr + 2 + rel:#08x}")
                i += 2
                continue
            if b == 0xE8:
                rel = struct.unpack_from("<i", code, i + 1)[0]
                print(f"  {addr:#08x}  call   -> {addr + 5 + rel:#08x}")
                i += 5
                continue
            i += 1
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
