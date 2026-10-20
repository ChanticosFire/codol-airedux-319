"""Poll global counters in the client without hooking anything.

Hooking near Add proved unreliable: the two attempts at 0xBBA440 each crashed the client after
two samples, and the one at 0xBBA418 replayed the SEH installation instruction, which may have
changed the very behaviour being measured.

0xE85CB0 is an exact tally of successful receives - it has exactly one write site, the add at
0xBB1734 on the success path. Polling it is a pure read and cannot perturb the program, so it
is the trustworthy way to decide whether successes happen in steady state.

    python tools/poll_counters.py --secs 60
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"

COUNTERS = {
    "success_lo": 0xE85CB0,   # incremented at 0xBB1734 on the success path
    "success_hi": 0xE85CB4,   # adc at 0xBB173D (64-bit style carry)
    "bytes_lo": 0xE85CA0,     # add [0xE85CA0], eax at 0xBB1725
    "bytes_hi": 0xE85CA4,     # adc at 0xBB172E
}


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read_u32(h, va: int) -> int | None:
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, 4, ctypes.byref(got)):
        return struct.unpack("<I", buf.raw)[0]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secs", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        print("OpenProcess failed")
        return 2
    try:
        print(f"pid={pid}  polling every {args.interval:g}s for {args.secs:g}s")
        print(f"{'t':>6}  {'success':>10}  {'delta':>8}  {'bytes':>12}")
        prev = None
        t0 = time.time()
        while time.time() - t0 < args.secs:
            lo = read_u32(h, COUNTERS["success_lo"])
            hi = read_u32(h, COUNTERS["success_hi"])
            blo = read_u32(h, COUNTERS["bytes_lo"])
            bhi = read_u32(h, COUNTERS["bytes_hi"])
            if lo is None:
                print("  client exited")
                return 0
            success = (hi << 32) | lo if hi is not None else lo
            nbytes = ((bhi or 0) << 32) | (blo or 0)
            delta = "" if prev is None else f"{success - prev:+d}"
            print(f"{time.time() - t0:6.1f}  {success:>10}  {delta:>8}  {nbytes:>12}")
            prev = success
            time.sleep(args.interval)
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
