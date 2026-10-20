"""Sentinel experiment: change the constant written at 0xBBA569 and watch for it.

Every anchor around Add s store either prevents the client starting or dies after one hit, so the
store s hit count has never been measurable. This changes only the immediate operand of
mov dword [ebx+0x120],2 - no hook, no control flow - to write 0xABCD1234 instead. Then polling
obj1 status for that value answers whether the store ever runs.

    python tools/sentinel_store.py --secs 45

Result: seeing the sentinel means the store executes and something replaces it afterwards;
never seeing it means the positive-count calls never reach that instruction.
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
STORE = 0xBBA569
ORIGINAL = bytes.fromhex("C7832001000002000000")        # mov dword [ebx+0x120], 2
SENTINEL = 0xABCD1234
PATCHED = bytes.fromhex("C78320010000") + struct.pack("<I", SENTINEL)


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
        # wait for the image to map, then patch before the store can run
        wait_img = time.time()
        live = read(h, STORE, len(ORIGINAL))
        while live != ORIGINAL and time.time() - wait_img < 60:
            time.sleep(0.02)
            live = read(h, STORE, len(ORIGINAL))
        if live != ORIGINAL:
            print(f"store bytes mismatch: want {ORIGINAL.hex()} got {live.hex()}")
            return 3
        if not write(h, STORE, PATCHED):
            print("patch failed")
            return 4
        print(f"patched {STORE:#x}: writes {SENTINEL:#010x} instead of 2 "
              f"(after {time.time() - wait_img:.2f}s)")

        seen_sentinel = 0
        t0 = time.time()
        last_note = 0.0
        while time.time() - t0 < args.secs:
            lobby = u32(h, 0xE85C68)
            if lobby is None:
                print("  process gone")
                return 0
            status = None
            if lobby:
                obj1 = u32(h, lobby + 0x1F8)
                if obj1:
                    status = u32(h, obj1 + 0x120)
            if status == SENTINEL:
                seen_sentinel += 1
                print(f"  t={time.time() - t0:6.2f}  SENTINEL OBSERVED  status={status:#010x}")
            now = time.time() - t0
            if now - last_note >= 5.0:
                print(f"  t={now:6.2f}  status={status!s:>12}  dw={u32(h, 0x84ABA40)}")
                last_note = now
            time.sleep(args.interval)

        print(f"\nsentinel observed {seen_sentinel} time(s)")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
