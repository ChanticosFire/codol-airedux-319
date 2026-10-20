"""Find every jump inside 0xBAD800 that targets a given address.

Static disassembly of the big pump function kept producing wrong conclusions because
the listing merges paths. This maps which jumps can reach each interesting site, so
the real entry branch can be identified instead of guessed.

    python tools/jump_map.py 0xBAE781 0xBAE7AA 0xBAE1AC
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
FUNC_LO, FUNC_HI = 0xBAD800, 0xBAE900


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


def jumps_in(h, lo: int, hi: int) -> list[tuple[int, int, str]]:
    out = []
    for va in range(lo, hi):
        b = read(h, va, 7)
        if len(b) < 2:
            continue
        tgt = None
        kind = None
        if b[0] == 0xE9:
            tgt, kind = va + 5 + struct.unpack_from("<i", b, 1)[0], "jmp32"
        elif b[0] == 0xEB:
            tgt, kind = va + 2 + struct.unpack_from("<b", b, 1)[0], "jmp8"
        elif b[0] == 0x0F and len(b) >= 6 and 0x80 <= b[1] <= 0x8F:
            tgt, kind = va + 6 + struct.unpack_from("<i", b, 2)[0], f"jcc32 {b[1]:#04x}"
        elif 0x70 <= b[0] <= 0x7F:
            tgt, kind = va + 2 + struct.unpack_from("<b", b, 1)[0], f"jcc8 {b[0]:#04x}"
        if tgt is not None:
            out.append((va, tgt, kind))
    return out


def main() -> int:
    targets = [int(a, 16) for a in sys.argv[1:]] or [0xBAE781, 0xBAE7AA, 0xBAE1AC]
    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    try:
        all_jumps = jumps_in(h, FUNC_LO, FUNC_HI)
        for t in targets:
            srcs = [(va, kind) for va, tgt, kind in all_jumps if tgt == t]
            print(f"{t:#x}: " + (", ".join(f"{va:#x} {kind}" for va, kind in srcs)
                                 if srcs else "(no direct jump)"))
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
