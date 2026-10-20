"""Sentinel on the second write of 2, to learn whether that branch ever runs.

0xBAE587 writes 2 into [ebx+0x1F4] with no conditional guard in front of it. Yet the field is almost always
observed as 1, which means either the branch never runs or one of the three unconditional stores of 1 resets it
before any sample lands.

Changing its immediate to a distinctive value answers which. If the poller ever sees it, the branch runs and the
resets are the obstacle; if it never does, some upstream precondition blocks entry.

    python tools/sentinel_1f4.py --secs 45

Original at 0xBAE587: C7 83 F4 01 00 00 02 00 00 00   mov dword [ebx+0x1F4], 2
Patched:              C7 83 F4 01 00 00 40 12 CD AB   mov dword [ebx+0x1F4], 0xABCD1240
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
SITE = 0xBAE587
ORIGINAL = bytes.fromhex("C783F401000002000000")
SENTINEL = 0xABCD1240
PATCHED = bytes.fromhex("C783F4010000") + struct.pack("<I", SENTINEL)


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
        live = read(h, SITE, len(ORIGINAL))
        while live != ORIGINAL and time.time() - wait_img < 60:
            time.sleep(0.02)
            live = read(h, SITE, len(ORIGINAL))
        if live != ORIGINAL:
            print(f"mismatch at {SITE:#x}: want {ORIGINAL.hex()} got {live.hex()}")
            return 3
        if not write(h, SITE, PATCHED):
            print("patch failed")
            return 4
        print(f"patched {SITE:#x}: writes {SENTINEL:#010x} into 1F4 (was {time.time() - wait_img:.2f}s)")

        seen = 0
        values: dict[int, int] = {}
        t0 = time.time()
        last_note = 0.0
        while time.time() - t0 < args.secs:
            lobby = u32(h, 0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            if lobby:
                v = u32(h, lobby + 0x1F4)
                if v is not None:
                    values[v] = values.get(v, 0) + 1
                    if v == SENTINEL:
                        seen += 1
                        print(f"  t={time.time() - t0:6.2f}  SENTINEL in 1F4")
                now = time.time() - t0
                if now - last_note >= 5.0:
                    print(f"  t={now:6.2f}  1F4={v!s:>12}  dw={u32(h, 0x84ABA40)}")
                    last_note = now
            time.sleep(args.interval)

        print(f"\nsentinel observed: {seen}")
        print("distinct 1F4 values seen:")
        for val, cnt in sorted(values.items(), key=lambda kv: -kv[1])[:6]:
            print(f"    {val:#010x}  x{cnt}")
        if seen:
            print("VERDICT: the branch runs; the resets are what keep 1F4 at 1")
        else:
            print("VERDICT: the branch never runs; an upstream precondition blocks it")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
