"""Find every `call rel32` that targets a given VA in the running client.

0x801910 is the routine the community patch names as the [111] trigger
("lsg-disconnect 0x7EE9DC erases the call to 0x801910"). Patching that one
call site did not stop the dialog, so scan the executable image for every
call that reaches it.

Usage: python runs/find_calls.py 0x801910 [seconds]
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
IMAGE_SIZE = 0x900000      # main module spans roughly 0x400000..0xD00000


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
    target = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x801910
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    print(f"pid={pid} target={target:#x}")
    deadline = time.time() + wait
    hits: set[int] = set()
    try:
        while time.time() < deadline:
            base = 0x400000
            chunk = 0x100000
            while base < 0x400000 + IMAGE_SIZE:
                data = read(h, base, chunk)
                if data:
                    needle = b"\xe8"
                    i = data.find(needle)
                    while i >= 0:
                        if i + 5 <= len(data):
                            rel = struct.unpack("<i", data[i + 1:i + 5])[0]
                            src = base + i
                            if (src + 5 + rel) & 0xFFFFFFFF == target:
                                hits.add(src)
                        i = data.find(needle, i + 1)
                base += chunk
            if hits:
                break
            time.sleep(3)
        if hits:
            for va in sorted(hits):
                print(f"call at {va:#010x}")
        else:
            print("no caller found in scanned range")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
