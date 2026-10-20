"""Read the patched sites while the client is running.

patch.json only proves the write landed; 1604220 may restore its own bytes
(there is precedent: forcing crypt/ready was rolled back within a second).
This samples the sites repeatedly so a revert becomes visible.
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
    ("lobby_pump_ok", 0x803699, "eb1f"),
    ("no_dw_delete", 0x803659, "909090909090"),
    ("account_force", 0x7F2A0A, "b8bc0200009090"),
    ("no_lsg_disconnect", 0x7EE9DC, "9090909090"),
    ("no_fatal_popup", 0x77C860, "c39090909090"),
    ("hide_connecting", 0x60C649, "b000"),
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


def read(h, va: int, n: int) -> str:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value].hex() if ok else "READ_FAILED"


def main() -> int:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
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
        while time.time() < deadline:
            row = {}
            for name, va, expect in SITES:
                actual = read(h, va, len(expect) // 2)
                row[name] = "ok" if actual == expect else actual
            print(time.strftime("%H:%M:%S"), json.dumps(row), flush=True)
            time.sleep(3)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
