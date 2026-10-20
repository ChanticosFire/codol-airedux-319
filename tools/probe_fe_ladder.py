"""Read every variable that gates the FE ladder (0x5EBFD0) in the live client.

Decoded ladder, from 他人文件参考/零补丁还债台账.md:

    entry: call 0x5EE7C0 (login-state query); eax != 1 -> return
    G1 = [0x82E1340], CS = [0x84ABA50]
    G1==0: firstlogin; on success push "cppFirstLogin"  -> G1=1
    G1==1: cmp CS,9        (must equal 9)
           call 0x730C50 (FE-loaded) must return 1
           [[0x3306D60]]+0xC must be 0
           [0x82E1346] must be 0
           [0x84ABAFC] must be non-zero (session ready)
           push "cppInLoginQueue" -> G1=2
    G1==2: call 0x5EBE10 (cppActivate) -> gate=1, G1=3

So it stalls unless all five conditions hold. This prints each of them.
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

BYTE_SITES = [
    ("G1 [0x82E1340]", 0x82E1340, "<B"),
    ("gate [0x82E1344]", 0x82E1344, "<B"),
    ("queue [0x82E1346]", 0x82E1346, "<B"),
    ("CS ui_state [0x84ABA50]", 0x84ABA50, "<I"),
    ("dw [0x84ABA40]", 0x84ABA40, "<I"),
    ("session_ready [0x84ABAFC]", 0x84ABAFC, "<I"),
    ("D_cond_ptr [0x3306D60]", 0x3306D60, "<I"),
    ("FE_obj [0xE69738]", 0xE69738, "<I"),
    ("bdobj [0xE69764]", 0xE69764, "<I"),
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
            for name, va, fmt in BYTE_SITES:
                size = struct.calcsize(fmt)
                data = read(h, va, size)
                if len(data) == size:
                    row[name] = struct.unpack(fmt, data)[0]
                else:
                    row[name] = None
            # dereference the D-condition pointer and read +0xC
            ptr = row.get("D_cond_ptr [0x3306D60]")
            if ptr:
                inner = read(h, ptr + 0xC, 4)
                row["D+0xC"] = struct.unpack("<I", inner)[0] if len(inner) == 4 else None
            else:
                row["D+0xC"] = None
            print(time.strftime("%H:%M:%S"), row, flush=True)
            time.sleep(4)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
