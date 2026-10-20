"""High-frequency sampling of [lobby+0x1F4] to detect oscillation.

The previous probe sampled once a second, which cannot distinguish a value that
is stuck at 1 from one that is rewritten every pump cycle. This samples as fast
as it can and reports the distribution plus every transition observed, along with
the lobby+0x1FC container pointer (which is rebuilt each cycle).

    python tools/sample_1f4.py 8          # sample for 8 seconds
    python tools/sample_1f4.py 8 --hz 200
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import collections
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
LOBBY_GLOBAL = 0xE85C68
OFF_1F4 = 0x1F4
OFF_1FC = 0x1FC
FE_STATE = 0xE59D20


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


def u32(h, va: int):
    d = read(h, va, 4)
    return struct.unpack("<I", d)[0] if len(d) == 4 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seconds", nargs="?", type=float, default=8.0)
    parser.add_argument("--hz", type=float, default=100.0)
    args = parser.parse_args()

    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    print(f"pid={pid} sampling {args.seconds:g}s at {args.hz:g} Hz")
    period = 1.0 / args.hz
    try:
        lobby = u32(h, LOBBY_GLOBAL)
        print(f"lobby = {lobby:#x}" if lobby else "lobby is null")
        if not lobby:
            return 4
        hist: collections.Counter = collections.Counter()
        transitions: list[tuple[float, int, int, int, int]] = []
        last = None
        last_ctr = None
        t0 = time.time()
        deadline = t0 + args.seconds
        samples = 0
        while time.time() < deadline:
            val = u32(h, lobby + OFF_1F4)
            ctr = u32(h, lobby + OFF_1FC)
            hist[val] += 1
            samples += 1
            if last is not None and (val != last or ctr != last_ctr):
                transitions.append((time.time() - t0, last, val, last_ctr, ctr))
                if len(transitions) <= 30:
                    print(f"  t={time.time() - t0:7.3f}s  1F4 {last} -> {val}"
                          f"   1FC {last_ctr:#x} -> {ctr:#x}"
                          if last_ctr is not None and ctr is not None
                          else f"  t={time.time() - t0:7.3f}s  1F4 {last} -> {val}")
            last, last_ctr = val, ctr
            time.sleep(period)
        fe = u32(h, FE_STATE)
        print(f"--- {samples} samples over {time.time() - t0:.2f}s ---")
        print(f"  distribution of [lobby+0x1F4]: "
              + ", ".join(f"{k}:{v}" for k, v in hist.most_common()))
        print(f"  transitions observed: {len(transitions)}")
        print(f"  final 1FC={last_ctr:#x}  FE_state={fe}")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
