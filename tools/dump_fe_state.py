"""Dump the FE state globals around the ladder variables.

0x82E1340 (G1) / 0x82E1344 (gate) / 0x82E1346 (queue) live here, and the
"取一个代号" screen is presumably driven by a neighbour. Sampling the whole
block before and after forcing firstlogin shows which byte flips.

    python tools/dump_fe_state.py 40
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
BASE = 0x82E1300
SIZE = 0x120


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
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    print(f"pid={pid} block {BASE:#x}..{BASE + SIZE:#x}")
    try:
        last = None
        deadline = time.time() + secs
        while time.time() < deadline:
            data = read(h, BASE, SIZE)
            if data and data != last:
                if last is None:
                    print("initial:")
                    for off in range(0, len(data), 16):
                        chunk = data[off:off + 16]
                        print(f"  {BASE + off:#010x}  {' '.join(f'{b:02x}' for b in chunk)}")
                else:
                    diffs = [i for i, (a, b) in enumerate(zip(last, data)) if a != b]
                    if diffs:
                        print("changed:", ", ".join(f"{BASE + i:#x}: {last[i]:02x}->{data[i]:02x}"
                                                    for i in diffs[:20]))
                last = data
            time.sleep(1.5)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
