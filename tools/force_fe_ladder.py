"""Nudge the FE ladder past its firstlogin step.

Decoded ladder (零补丁还债台账.md):

    G1 = [0x82E1340]
    G1==0: call 0x6BBF30 (firstlogin); al==0 -> stays 0; al==1 -> UI -> G1=1
    G1==1: CS must be 9, 0x730C50 (FE-loaded) must return 1,
           [[0x3306D60]]+0xC == 0, [0x82E1346] == 0, [0x84ABAFC] != 0
           -> push "cppInLoginQueue" -> G1=2
    G1==2: call 0x5EBE10 (cppActivate) -> gate=1, G1=3

Live sampling shows G1 stays 0 while CS=9 and dw=5, i.e. 0x6BBF30 never
returns 1 for this offline session. Writing G1=1 lets the ladder attempt its
own G1==1 checks instead of stalling at the firstlogin query.

This only writes process memory; nothing on disk is touched.
"""
from __future__ import annotations

import argparse
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
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
G1 = 0x82E1340
GATE = 0x82E1344
QUEUE = 0x82E1346
SESSION_READY = 0x84ABAFC
CS = 0x84ABA50


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


def write(h, va: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data, len(data))
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def show(h, label: str) -> None:
    g1 = read(h, G1, 1)
    gate = read(h, GATE, 1)
    ready = read(h, SESSION_READY, 4)
    cs = read(h, CS, 4)
    print(f"{label:8s} G1={g1[0] if g1 else None} gate={gate[0] if gate else None} "
          f"session_ready={struct.unpack('<I', ready)[0] if len(ready) == 4 else None} "
          f"CS={struct.unpack('<I', cs)[0] if len(cs) == 4 else None}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60,
                        help="keep nudging for this long")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--set-ready", action="store_true",
                        help="also write 1 into [0x84ABAFC] (session ready)")
    args = parser.parse_args()

    pid = find_pid()
    if not pid:
        print("client not running", file=sys.stderr)
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error(), file=sys.stderr)
        return 3
    print(f"pid={pid}")
    try:
        show(h, "before")
        deadline = time.time() + args.seconds
        last = None
        while time.time() < deadline:
            g1 = read(h, G1, 1)
            if g1 and g1[0] == 0:
                write(h, G1, b"\x01")
            if args.set_ready:
                ready = read(h, SESSION_READY, 4)
                if len(ready) == 4 and struct.unpack("<I", ready)[0] == 0:
                    write(h, SESSION_READY, struct.pack("<I", 1))
            state = (read(h, G1, 1)[:1], read(h, GATE, 1)[:1])
            if state != last:
                show(h, "now")
                last = state
            time.sleep(args.interval)
        show(h, "after")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
