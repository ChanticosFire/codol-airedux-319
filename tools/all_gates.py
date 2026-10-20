"""Neutralise all three pump-side guards as well, and watch whether 1F4 finally becomes 2.

Round 149 made Add behave by nop'ing two filters, and the status reached 2. But 1F4 stayed at 1 because three byte flags on
the pump's frame divert to the reset at 0xBAE7B4 before execution ever reaches the status check at 0xBAE30F.

Those three checks are at 0xBAE2DD, 0xBAE2EA and 0xBAE2F7, each comparing a local byte against zero with a six-byte je.
Nop'ing all three lets execution continue regardless, and if 1F4 then becomes 2 the guards are confirmed; restoring them one
at a time would then identify which one fires.

All five patches are pure data edits:

  0xBBA465  0F 84 3A 01 00 00  ->  90 x6     (Add filter A)
  0xBBA483  0F 84 1C 01 00 00  ->  90 x6     (Add filter B)
  0xBAE2E4  0F 84 CA 04 00 00  ->  90 x6     (pump guard A, [ebp-0x988])
  0xBAE2F1  0F 84 BD 04 00 00  ->  90 x6     (pump guard B, [ebp-0x989])
  0xBAE2FE  0F 84 B0 04 00 00  ->  90 x6     (pump guard C, [ebp-0x986])

    python tools/all_gates.py --secs 60
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
NOP6 = bytes.fromhex("909090909090")
PATCHES = [
    (0xBBA465, bytes.fromhex("0F843A010000"), NOP6, "Add filter A"),
    (0xBBA483, bytes.fromhex("0F841C010000"), NOP6, "Add filter B"),
    (0xBAE2E4, bytes.fromhex("0F84CA040000"), NOP6, "pump guard A"),
    (0xBAE2F1, bytes.fromhex("0F84BD040000"), NOP6, "pump guard B"),
    (0xBAE2FE, bytes.fromhex("0F84B0040000"), NOP6, "pump guard C"),
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
    ap.add_argument("--secs", type=float, default=60.0)
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
        while time.time() - wait_img < 60:
            if all(read(h, addr, len(o)) == o for addr, o, _, _ in PATCHES):
                break
            time.sleep(0.02)
        else:
            print("image not ready")
            return 3

        for addr, _o, new, label in PATCHES:
            if not write(h, addr, new):
                print(f"patch failed at {addr:#x}")
                return 4
            print(f"patched {addr:#x}  {label}")

        last = None
        t0 = time.time()
        saw2 = 0
        while time.time() - t0 < args.secs:
            lobby = u32(h, 0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            obj1 = u32(h, lobby + 0x1F8) if lobby else 0
            status = u32(h, obj1 + 0x120) if obj1 else None
            idx = u32(h, obj1 + 0x130) if obj1 else None
            f14 = u32(h, lobby + 0x1F4) if lobby else None
            fe = u32(h, 0xE59D20)
            g1 = u32(h, 0x82E1340)
            if f14 == 2:
                saw2 += 1
            key = (status, idx, f14, fe, g1)
            if key != last:
                last = key
                print(f"  t={time.time() - t0:6.2f}  status={status!s:>6}  idx={idx!s:>5}  "
                      f"1F4={f14!s:>4}  FE={fe!s:>5}  G1={g1!s:>4}  dw={u32(h, 0x84ABA40)}")
            time.sleep(args.interval)

        print(f"\nsamples with 1F4==2: {saw2}")
        print(f"final: {last}")
        if saw2:
            print("VERDICT: the pump guards were the blocker; 1F4 reaches 2")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
