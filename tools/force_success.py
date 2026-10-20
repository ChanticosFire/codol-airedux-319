"""Bisect: force the success branch and see whether the store is reachable at all.

Three observations contradict each other:
  - the histogram says the count is 3 in 91.4% of samples (hook-based, least trustworthy)
  - inverting the branch shows the flow behaves as if taken (data edit, moderately trustworthy)
  - the sentinel shows the store at 0xBBA569 never runs (data edit, most trustworthy)

This forces the branch unconditionally into the success block and simultaneously replaces the store s immediate
with a sentinel. If the sentinel then appears, the success block works and only the branch condition was ever
wrong. If it still does not appear, something inside the block prevents reaching the store.

Patches:
  0xBBA442  0F 8E 7B 01 00 00  ->  E9 01 00 00 00 90    jle 0xBBA5C3  ->  jmp 0xBBA448
  0xBBA569  C7 83 20 01 00 00 02 00 00 00
            C7 83 20 01 00 00 34 12 CD AB                store of 2  ->  store of 0xABCD1234

    python tools/force_success.py --secs 45
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
BRANCH = 0xBBA442
BRANCH_ORIG = bytes.fromhex("0F8E7B010000")
SUCCESS = 0xBBA448
STORE = 0xBBA569
STORE_ORIG = bytes.fromhex("C7832001000002000000")
REP = 0xBBA4F2
REP_ORIG = bytes.fromhex("F3A5")
REP_PATCH = bytes.fromhex("9090")
SENTINEL = 0xABCD1234


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
        while time.time() - wait_img < 60:
            b = read(h, BRANCH, len(BRANCH_ORIG))
            s = read(h, STORE, len(STORE_ORIG))
            if b == BRANCH_ORIG and s == STORE_ORIG:
                break
            time.sleep(0.02)
        else:
            print(f"image not ready: branch={b.hex()} store={s.hex()}")
            return 3

        rel = SUCCESS - (BRANCH + 5)
        branch_patch = b"\xE9" + struct.pack("<i", rel) + b"\x90"
        store_patch = bytes.fromhex("C78320010000") + struct.pack("<I", SENTINEL)
        if not write(h, BRANCH, branch_patch):
            print("branch patch failed")
            return 4
        if not write(h, STORE, store_patch):
            print("store patch failed")
            return 4
        rep_live = read(h, REP, len(REP_ORIG))
        if rep_live == REP_ORIG:
            write(h, REP, REP_PATCH)
            print(f"patched rep    {REP:#x}: F3A5 -> 9090 (rep movsd skipped)")
        else:
            print(f"rep site not as expected: {rep_live.hex()}")
        print(f"patched branch {BRANCH:#x}: jle -> jmp {SUCCESS:#x} ({branch_patch.hex()})")
        print(f"patched store  {STORE:#x}: 2 -> {SENTINEL:#010x}")

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
                    if status == SENTINEL:
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
            print("VERDICT: the success block works; only the branch condition was ever wrong")
        elif states and states[-1] == 3:
            print("VERDICT: forcing entry still fails to reach the store, so the block itself is broken")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
