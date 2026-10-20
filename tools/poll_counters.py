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
    ap.add_argument("--wait", type=float, default=0.0,
                    help="seconds to wait for the client to appear before sampling")
    ap.add_argument("--with-state", action="store_true",
                    help="also read lobby/obj1 status+index through [0xE85C68]")
    ap.add_argument("--anchor-dw", action="store_true",
                    help="wait until dw at 0x84ABA40 equals 5 before sampling starts")
    ap.add_argument("--anchor-timeout", type=float, default=90.0)
    ap.add_argument("--only-changes", action="store_true",
                    help="print a line only when one of the sampled values changes")
    args = ap.parse_args()

    pid = 0
    deadline = time.time() + args.wait
    while True:
        pid = find_pid()
        if pid:
            break
        if time.time() >= deadline:
            print("client did not appear")
            return 2
        time.sleep(0.02)
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        print("OpenProcess failed")
        return 2
    try:
        if args.anchor_dw:
            # the window being studied begins when the front end reaches dw==5, not when the
            # process appears: a dozen seconds of loading sit between the two.
            t_wait = time.time()
            while time.time() - t_wait < args.anchor_timeout:
                dw = read_u32(h, 0x84ABA40)
                if dw == 5:
                    print(f"  anchor reached: dw=5 after {time.time() - t_wait:.2f}s")
                    break
                time.sleep(0.02)
            else:
                print(f"  anchor timeout, dw={read_u32(h, 0x84ABA40)}")
                return 3
        print(f"pid={pid}  polling every {args.interval:g}s for {args.secs:g}s")
        hdr = f"{'t':>6}  {'success':>10}  {'delta':>8}  {'bytes':>12}"
        if args.with_state:
            hdr += f"  {'status':>6}  {'idx':>4}  {'1F4':>4}"
        print(hdr)
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
            line = f"{time.time() - t0:6.2f}  {success:>10}  {delta:>8}  {nbytes:>12}"
            if args.with_state:
                lobby = read_u32(h, 0xE85C68)
                status = idx = f14 = None
                if lobby:
                    o1 = read_u32(h, lobby + 0x1F8)
                    if o1:
                        status = read_u32(h, o1 + 0x120)
                        idx = read_u32(h, o1 + 0x130)
                    f14 = read_u32(h, lobby + 0x1F4)
                line += f"  {status!s:>6}  {idx!s:>4}  {f14!s:>4}"
            if args.only_changes:
                key = (success, nbytes, status, idx, f14)
                if key != getattr(main, "_last_key", None):
                    main._last_key = key
                    print(line)
            else:
                print(line)
            prev = success
            time.sleep(args.interval)
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
