"""Poll the fastfile request table while a demo plays.

    python tools/watch_fastfile_table.py --seconds 35

The table lives at 0x1D06440 (0x44 bytes per entry, name at +0x00) and its count
at 0x239B11C.  Watching it during demo playback shows the exact moment the map
fastfile is queued, without relying on breakpoints (which proved unreliable in
the reused runtime).
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

TABLE = 0x1D06440
COUNT = 0x239B11C
ENTRY = 0x44
NET_STATE = 0x76446B0


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=35)
    ap.add_argument("--interval", type=float, default=0.15)
    ap.add_argument("--output")
    args = ap.parse_args()
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int | None:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return None
        return struct.unpack("<I", buf.raw)[0]

    def cstr(address: int, size: int = 96) -> str:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return ""
        return buf.raw.split(b"\0")[0].decode("latin-1", "replace")

    rows = []
    last = None
    start = time.time()
    while time.time() - start < args.seconds:
        count = u32(COUNT) or 0
        names = []
        for i in range(min(count, 4)):
            names.append(cstr(TABLE + i * ENTRY))
        net = u32(NET_STATE)
        key = (count, tuple(names), net)
        if key != last:
            last = key
            row = {"t": round(time.time() - start, 2), "count": count,
                   "names": names, "net_state": net}
            rows.append(row)
            print(json.dumps(row), flush=True)
        time.sleep(args.interval)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
