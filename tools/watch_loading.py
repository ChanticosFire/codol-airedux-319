"""Poll the loading object fields (+0x5E8/+0x5EC/+0x5F0) and print every change.

    python tools/watch_loading.py --seconds 60

Resolves the singleton through [0x8269774] -> +0x4F4 -> sub, so it works across
runs without hardcoding heap addresses.
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

SINGLETON = 0x8269774
UI_STATE = 0x84ABA50
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
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--output")
    args = ap.parse_args()
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int | None:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return None
        return struct.unpack("<I", buf.raw)[0]

    rows = []
    last = None
    start = time.time()
    while time.time() - start < args.seconds:
        singleton = u32(SINGLETON)
        ui = u32(UI_STATE)
        net = u32(NET_STATE)
        sub = None
        values = None
        if singleton:
            sub = u32(singleton + 0x4F4)
            if sub:
                values = (u32(sub + 0x5E8), u32(sub + 0x5EC), u32(sub + 0x5F0),
                          u32(sub + 0xC8), u32(sub + 0x644))
        row = {"t": round(time.time() - start, 2), "ui": ui, "net": net,
               "singleton": singleton, "sub": sub, "fields": values}
        key = (ui, net, values)
        if key != last:
            last = key
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        time.sleep(args.interval)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
