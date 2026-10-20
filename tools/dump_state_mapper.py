"""Dump the ui_state mapper region and its jump table in the live client.

On 1649370, 0x7F25B0 maps ui_state through a jump table at 0x7F25DC:
0 -> 4 (fail), 1..4 -> 1, 5 -> 3 (success). 1604220 samples ui=9, which is
outside that range, so either the address moved or the mapping changed.
"""
from __future__ import annotations

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
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 45
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
        for label, va, n in (("0x7F25B0 mapper", 0x7F25B0, 0x60),
                             ("0x7F25DC table", 0x7F25DC, 0x30),
                             ("0x823000 nearby", 0x823000, 0x20)):
            data = read(h, va, n)
            print(f"--- {label} {va:#x} ({len(data)}B)")
            print(data.hex(" "))
        # global ui_state and friends
        for label, va in (("dw", 0x84ABA40), ("ui_state", 0x84ABA50),
                          ("prev_ui", 0x84ABA54), ("account_error", 0x84ABA5C)):
            data = read(h, va, 4)
            if data:
                print(f"{label:14s} {va:#x} = {struct.unpack('<I', data)[0]}")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
