"""Neutralise both filters in Add's success block and watch for the sentinel on the store.

Round 147 established that the two branches at 0xBBA465 and 0xBBA483 both jump to 0xBBA5A5, past the store of 2 at
0xBBA569, and both encode as six-byte je rel32. Replacing each with six nops makes them never branch, without changing
lengths or downstream offsets.

If the sentinel then appears, those branches are the blocker and the remaining question is which one fires and why -
either a duplicate entry or a failed append. If it still does not appear, a deeper filter exists.

    python tools/no_filters.py --secs 45
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
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
PATCHES = [
    (0xBBA465, bytes.fromhex("0F843A010000"), bytes.fromhex("909090909090"), "filter A (dup check)"),
    (0xBBA483, bytes.fromhex("0F841C010000"), bytes.fromhex("909090909090"), "filter B (append)"),
    (0xBBA569, bytes.fromhex("C7832001000002000000"),
     bytes.fromhex("C78320010000") + struct.pack("<I", 0xABCD1234), "store -> sentinel"),
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


def write(h, va: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data, len(data))
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def u32(h, va: int) -> int | None:
    raw = read(h, va, 4)
    return struct.unpack("<I", raw)[0] if len(raw) == 4 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secs", type=float, default=45.0)
    ap.add_argument("--wait", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=0.02)
    args = ap.parse_args()

    deadline = time.time() + args.wait
    pid = 0
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            break
        time.sleep(0.02)
    if not pid:
        print("client did not appear")
        return 2

    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 2
    try:
        wait_img = time.time()
        ready = False
        while time.time() - wait_img < 60:
            if all(read(h, addr, len(orig)) == orig for addr, orig, _, _ in PATCHES):
                ready = True
                break
            time.sleep(0.02)
        if not ready:
            print("image not ready")
            return 3

        for addr, _orig, new, label in PATCHES:
            if not write(h, addr, new):
                print(f"patch failed at {addr:#x}")
                return 4
            print(f"patched {addr:#x}  {label}")

        states: list[int] = []
        saw = 0
        t0 = time.time()
        while time.time() - t0 < args.secs:
            lobby = u32(h, 0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            if lobby:
                obj1 = u32(h, lobby + 0x1F8)
                if obj1:
                    status = u32(h, obj1 + 0x120)
                    if status == 0xABCD1234:
                        saw += 1
                        print(f"  t={time.time() - t0:6.2f}  SENTINEL  status={status:#010x}")
                    if status is not None and (not states or states[-1] != status):
                        states.append(status)
                        print(f"  t={time.time() - t0:6.2f}  status={status:#010x}  "
                              f"idx={u32(h, obj1 + 0x130)}  dw={u32(h, 0x84ABA40)}")
            time.sleep(args.interval)

        print(f"\nstatus sequence: {[hex(x) for x in states]}")
        print(f"sentinel samples: {saw}")
        if saw:
            print("VERDICT: the two filters were the blocker; the store is reachable")
        elif states and states[-1] == 3:
            print("VERDICT: still ending at 3, so a deeper filter exists")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
