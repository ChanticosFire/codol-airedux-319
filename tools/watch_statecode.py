"""Watch the server-list state code, waiting for the client to appear first.

Round 173 tried the type 0x15 reply but polled immediately after a non-blocking start, so the process had not
been created yet and every read failed. This waits for the image, then samples the state code at [serverlist+0x1A0]
and reports every transition.

    python tools/watch_statecode.py --secs 45
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
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secs", type=float, default=45.0)
    ap.add_argument("--wait", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=0.02)
    args = ap.parse_args()

    deadline = time.time() + args.wait
    h = None
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            h = k32.OpenProcess(PROCESS_ALL, False, pid)
            if h:
                # the image maps a few seconds after the process appears
                probe = ctypes.create_string_buffer(4)
                got = ctypes.c_size_t()
                ok = k32.ReadProcessMemory(h, ctypes.c_void_p(0xE85C68), probe, 4,
                                           ctypes.byref(got))
                if ok and got.value == 4:
                    break
                k32.CloseHandle(h)
                h = None
        time.sleep(0.05)
    if not h:
        print("client never became readable")
        return 2

    def rd(va: int, n: int = 4) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else b""

    def u32(va: int) -> int | None:
        raw = rd(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

    try:
        last = None
        codes: dict[int | None, int] = {}
        saw4 = 0
        t0 = time.time()
        while time.time() - t0 < args.secs:
            lobby = u32(0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            if lobby:
                sl = u32(lobby + 0x1FC)
                o1 = u32(lobby + 0x1F8)
                code = u32(sl + 0x1A0) if sl else None
                r19c = u32(sl + 0x19C) if sl else None
                status = u32(o1 + 0x120) if o1 else None
                f14 = u32(lobby + 0x1F4)
                dw = u32(0x84ABA40)
                codes[code] = codes.get(code, 0) + 1
                if code == 4:
                    saw4 += 1
                key = (code, r19c, status, f14, dw)
                if key != last:
                    last = key
                    print(f"  t={time.time() - t0:6.2f}  1A0={code!s:>4}  19C={r19c!s:>8}  "
                          f"status={status!s:>4}  1F4={f14!s:>4}  dw={dw!s:>3}")
            time.sleep(args.interval)

        print(f"\n  state codes seen: {codes}")
        print(f"  samples with 1A0==4: {saw4}")
        if saw4:
            print("VERDICT: the type 0x15 reply advanced the list state to 4")
        else:
            print("VERDICT: the reply did not reach the parser, or was rejected")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
