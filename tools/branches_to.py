"""List every branch that targets an address, scanning both short and near forms.

find_calls only resolves call rel32. A bypass into the function epilogue could come from any conditional
or unconditional jump, so this scans a range for E9 (jmp rel32), EB (jmp rel8), 0F 8x (jcc rel32),
7x (jcc rel8) and also E8 (call rel32) for completeness, reporting which ones land on the target.

    python tools/branches_to.py 0xBBA635 --lo 0xBB9000 --hi 0xBBC000
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

JCC_NAMES = ["o", "no", "b", "ae", "e", "ne", "be", "a",
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
    ap.add_argument("target", help="target address in hex")
    ap.add_argument("--lo", default="0xBB9000")
    ap.add_argument("--hi", default="0xBBC000")
    args = ap.parse_args()

    target = int(args.target, 0)
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
        hits = []
        i = 0
        n = len(code)
        while i < n - 6:
            b = code[i]
            addr = lo + i
            # E9 / E8 : rel32
            if b in (0xE9, 0xE8) and i + 5 <= n:
                rel = struct.unpack_from("<i", code, i + 1)[0]
                tgt = addr + 5 + rel
                if tgt == target:
                    hits.append((addr, "jmp" if b == 0xE9 else "call", 5))
                i += 1
                continue
            # 0F 8x : jcc rel32
            if b == 0x0F and i + 6 <= n and 0x80 <= code[i + 1] <= 0x8F:
                rel = struct.unpack_from("<i", code, i + 2)[0]
                tgt = addr + 6 + rel
                if tgt == target:
                    cc = JCC_NAMES[code[i + 1] - 0x80]
                    hits.append((addr, f"j{cc}", 6))
                i += 1
                continue
            # EB : jmp rel8
            if b == 0xEB and i + 2 <= n:
                rel = struct.unpack_from("<b", code, i + 1)[0]
                if addr + 2 + rel == target:
                    hits.append((addr, "jmp short", 2))
                i += 1
                continue
            # 7x : jcc rel8
            if 0x70 <= b <= 0x7F and i + 2 <= n:
                rel = struct.unpack_from("<b", code, i + 1)[0]
                if addr + 2 + rel == target:
                    cc = JCC_NAMES[b - 0x70]
                    hits.append((addr, f"j{cc} short", 2))
                i += 1
                continue
            i += 1

        print(f"scan {lo:#x}..{hi:#x} for branches to {target:#x}")
        print(f"  {len(hits)} hit(s)")
        for addr, kind, size in hits:
            ctx = read(h, addr, size + 3)
            print(f"    {addr:#08x}  {kind:<12} {ctx.hex()}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
