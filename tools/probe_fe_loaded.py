"""Sample the variables that gate FE-loaded (0x730C50).

0x730C50 returns 1 only when every one of these holds:

    [0xE59D20] in {4, 6}          frontend state
    0x803700 != 0                 object lookup
    0xB7A680(obj) == 2            object predicate
    0xB7A6F0(obj) != 0            object predicate
    [0x84ABABC] == 1              script state
    0x7F68A0(obj+0x11150) != 0    check A
    0x7F68A0(obj+0x10) != 0       check B
    [0x82C4A86] != 0              final flag

Anything false and FE stays unloaded, which in turn blocks onboarded and the
FE ladder. This prints the cheap globals; the two 0x7F68A0 calls need the
object, so it also dereferences 0x803700 once to report the object pointer.

    python tools/probe_fe_loaded.py 40
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

U32 = [
    ("FE_state [0xE59D20]", 0xE59D20),
    ("script [0x84ABABC]", 0x84ABABC),
    ("ui_lstate [0x84ABA50]", 0x84ABA50),
    ("dw [0x84ABA40]", 0x84ABA40),
]
U8 = [
    ("final [0x82C4A86]", 0x82C4A86),
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
    print(f"pid={pid}")
    try:
        deadline = time.time() + secs
        last = None
        while time.time() < deadline:
            row = {}
            for name, va in U32:
                d = read(h, va, 4)
                row[name] = struct.unpack("<I", d)[0] if len(d) == 4 else None
            for name, va in U8:
                d = read(h, va, 1)
                row[name] = d[0] if d else None
            state = tuple(row.values())
            if state != last:
                print(time.strftime("%H:%M:%S"), row, flush=True)
                last = state
            time.sleep(1.0)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
