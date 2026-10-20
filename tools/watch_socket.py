"""Watch lobby+4 from the earliest readable moment to see whether a socket ever exists.

Round 177 found the send failing because the handle at lobby+4 is zero. The remaining question is whether it is
created and closed, or never created at all. Sampling begins as soon as the module is mapped, before the lobby
object even exists, and records every distinct value along with the state code once it appears.

    python tools/watch_socket.py --secs 45
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
    ap.add_argument("--wait", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=0.01)
    args = ap.parse_args()

    deadline = time.time() + args.wait
    h = None
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            h = k32.OpenProcess(PROCESS_ALL, False, pid)
            if h:
                probe = ctypes.create_string_buffer(4)
                got = ctypes.c_size_t()
                if k32.ReadProcessMemory(h, ctypes.c_void_p(0xE85C68), probe, 4,
                                         ctypes.byref(got)) and got.value == 4:
                    break
                k32.CloseHandle(h)
                h = None
        time.sleep(0.005)
    if not h:
        print("client never became readable")
        return 2

    def rd(va: int, n: int) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else b""

    def u32(va: int) -> int | None:
        raw = rd(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

    try:
        last = None
        socket_values: dict[int | None, int] = {}
        nonzero = 0
        t0 = time.time()
        while time.time() - t0 < args.secs:
            lobby = u32(0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            sock = u32(lobby + 4) if lobby else None
            code = None
            f14 = None
            if lobby:
                sl = u32(lobby + 0x1FC)
                code = u32(sl + 0x1A0) if sl else None
                f14 = u32(lobby + 0x1F4)
            socket_values[sock] = socket_values.get(sock, 0) + 1
            if sock not in (None, 0, 0xFFFFFFFF):
                nonzero += 1
                print(f"  t={time.time() - t0:6.2f}  *** SOCKET NONZERO  lobby+4={sock:#x}")
            key = (sock, code, f14)
            if key != last:
                last = key
                print(f"  t={time.time() - t0:6.2f}  lobby+4={sock!s:>10}  "
                      f"1A0={code!s:>4}  1F4={f14!s:>3}  dw={u32(0x84ABA40)!s:>3}")
            time.sleep(args.interval)

        print(f"\n  distinct lobby+4 values: {socket_values}")
        print(f"  samples with a live socket: {nonzero}")
        if nonzero:
            print("VERDICT: a socket existed at some point")
        else:
            print("VERDICT: lobby+4 was never a valid socket handle")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
