"""Read the nine lobby-pump patch sites named by the community report.

From the 2026-10-20 note, the pump patch has two groups:

  A) bypass handshake failure jumps: 0xBBA295, 0xBBA29D, 0xBBA276, 0xBBAD4D
  B) replace five hardcoded "write -2" (failure) sites with 1:
     0xBADC26, 0xBADDDA+6, 0xBAE74E+6, 0xBAE766+6, 0xBAE7AA+6

Before patching we must read what is actually there, because "write -2" is
`mov dword [reg+off], -2` (C7 4x xx FEFFFFFF or C7 8x xx xx xx xx) and the
replacement has to keep the same instruction length.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import sys
import time
from pathlib import Path

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"

SITES = [
    ("jump_bb_a295", 0xBBA295),
    ("jump_bb_a29d", 0xBBA29D),
    ("jump_bb_a276", 0xBBA276),
    ("jump_bb_ad4d", 0xBBAD4D),
    ("write_badc26", 0xBADC26),
    ("write_baddda_plus6", 0xBADDDA + 6),
    ("write_bae74e_plus6", 0xBAE74E + 6),
    ("write_bae766_plus6", 0xBAE766 + 6),
    ("write_bae7aa_plus6", 0xBAE7AA + 6),
]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int = 16) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def main() -> int:
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    print(f"pid={pid}")
    try:
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(3)
        for name, va in SITES:
            data = read(h, va, 16)
            print(f"{name:22s} {va:#010x} {data.hex(' ')}")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
