"""Invert the branch at 0xBBA442 and observe which way the program actually goes.

The contradiction is now sharp: the histogram says [ebp+0x94] is 3 in 91.4 percent of samples, yet forcing an
early return at 0xBBA442 keeps the status at 1, which means in normal operation the jle IS taken and edi must be
non-positive.

Inverting the condition settles it in one run. Replace 0F 8E (jle) with 0F 8F (jg), leaving the target and
length identical:

  if edi <= 0 in reality   -> jg is NOT taken -> control enters the body -> should reach the store of 2
                                                                          -> status becomes 2 (or the
                                                                             sentinel, if that patch is on)
  if edi > 0 in reality    -> jg IS taken -> jumps to 0xBBA5C3 -> same as today -> status ends at 3

So a status of 2 proves the count is genuinely non-positive and the histogram was measuring something stale;
a status of 3 proves the count really is positive and something else diverts control before the store.

    python tools/invert_branch.py --secs 45
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
SITE = 0xBBA442
ORIGINAL = bytes.fromhex("0F8E7B010000")     # jle 0xBBA5C3
INVERTED = bytes.fromhex("0F8F7B010000")     # jg  0xBBA5C3


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
    ap.add_argument("--interval", type=float, default=0.05)
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
        live = read(h, SITE, len(ORIGINAL))
        while live != ORIGINAL and time.time() - wait_img < 60:
            time.sleep(0.02)
            live = read(h, SITE, len(ORIGINAL))
        if live != ORIGINAL:
            print(f"mismatch at {SITE:#x}: want {ORIGINAL.hex()} got {live.hex()}")
            return 3
        if not write(h, SITE, INVERTED):
            print("patch failed")
            return 4
        print(f"patched {SITE:#x}: jle -> jg ({INVERTED.hex()}, was {time.time() - wait_img:.2f}s)")

        states: list[int] = []
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
                    idx = u32(h, obj1 + 0x130)
                    if status is not None and (not states or states[-1] != status):
                        states.append(status)
                        print(f"  t={time.time() - t0:6.2f}  status={status}  idx={idx}  "
                              f"dw={u32(h, 0x84ABA40)}")
            time.sleep(args.interval)

        print(f"\nstatus sequence: {states}")
        if 2 in states:
            print("VERDICT: edi was non-positive -> the count really is <= 0 in normal operation")
        elif states and states[-1] == 3:
            print("VERDICT: edi was positive -> the count is > 0 but control still avoids the store")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
