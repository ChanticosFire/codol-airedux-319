"""Read the address/port fields the sender uses, to test why sendto fails.

Round 173 traced the send down to 0xBB1420 and found that the port comes from a word at this+0x80 via 0xB754C0. If that
field is zero, sendto fails and the caller stores 5. This reads the fields around it while the client runs, both without
and with the type 0x15 reply, and prints them alongside the state code.

    python tools/read_addr.py --secs 30
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secs", type=float, default=30.0)
    ap.add_argument("--wait", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=0.05)
    args = ap.parse_args()

    deadline = time.time() + args.wait
    h = None
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            h = k32.OpenProcess(PROCESS_ALL, False, pid)
            if h:
                probe = ctypes.create_string_buffer(4)
                got = ctypes.c_size_t()
                if k32.ReadProcessMemory(h, ctypes.c_void_p(0xE85C68), probe, 4,
                                         ctypes.byref(got)) and got.value == 4:
                    break
                k32.CloseHandle(h)
                h = None
        time.sleep(0.05)
    if not h:
        print("client never became readable")
        return 2

    def rd(va: int, n: int) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else b""

    def u32(va: int) -> int | None:
        raw = rd(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

    def u16(va: int) -> int | None:
        raw = rd(va, 2)
        return struct.unpack("<H", raw)[0] if len(raw) == 2 else None

    try:
        last = None
        t0 = time.time()
        while time.time() - t0 < args.secs:
            lobby = u32(0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            if lobby:
                sl = u32(lobby + 0x1FC)
                if sl:
                    code = u32(sl + 0x1A0)
                    port_80 = u16(sl + 0x80)
                    d_7c = u32(sl + 0x7C)
                    d_84 = u32(sl + 0x84)
                    d_88 = u32(sl + 0x88)
                    f14 = u32(lobby + 0x1F4)
                    key = (code, port_80, d_7c, d_84, d_88, f14)
                    if key != last:
                        last = key
                        print(f"  t={time.time() - t0:6.2f}  1A0={code!s:>4}  "
                              f"[+0x80]={port_80!s:>6}  [+0x7C]={d_7c!s:>10}  "
                              f"[+0x84]={d_84!s:>10}  [+0x88]={d_88!s:>10}  1F4={f14}")
            time.sleep(args.interval)
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
