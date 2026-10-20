"""Keep only the two filter nops and watch whether the status becomes 2 and holds.

The sentinel proved the store at 0xBBA569 is reachable once the branches at 0xBBA465 and 0xBBA483 stop firing. This
run drops the sentinel so the store writes its real value, and follows the consequences: does obj1 status become 2,
does it stay, does the pump then write 2 into 1F4 at 0xBAE587, and does the front end advance.

    python tools/real_gate.py --secs 60
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
    (0xBBA465, bytes.fromhex("0F843A010000"), bytes.fromhex("909090909090"), "filter A"),
    (0xBBA483, bytes.fromhex("0F841C010000"), bytes.fromhex("909090909090"), "filter B"),
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
            if all(read(h, addr, len(orig)) == orig for addr, orig, _, _ in PATCHES):
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
        saw_two = 0
        while time.time() - t0 < args.secs:
            lobby = u32(h, 0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            if lobby:
                obj1 = u32(h, lobby + 0x1F8)
                status = idx = None
                if obj1:
                    status = u32(h, obj1 + 0x120)
                    idx = u32(h, obj1 + 0x130)
                f14 = u32(h, lobby + 0x1F4)
                fe = u32(h, 0xE59D20)
                g1 = u32(h, 0x82E1340)
                if status == 2:
                    saw_two += 1
                key = (status, idx, f14, fe, g1)
                if key != last:
                    last = key
                    print(f"  t={time.time() - t0:6.2f}  status={status!s:>6}  idx={idx!s:>5}  "
                          f"1F4={f14!s:>4}  FE={fe!s:>5}  G1={g1!s:>4}  dw={u32(h, 0x84ABA40)}")
            time.sleep(args.interval)

        print(f"\nsamples with status==2: {saw_two}")
        print(f"final: status={last[0] if last else None} 1F4={last[2] if last else None} "
              f"FE={last[3] if last else None} G1={last[4] if last else None}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
