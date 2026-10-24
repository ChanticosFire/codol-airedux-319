"""Poll the client's weapon-definition counter and log every change.

    python tools/watch_weapon_count.py --seconds 40 --interval 0.2

`0x1988634` is incremented by 0x42F432 whenever a composite weapon definition is
created.  Watching it during a real connect shows whether the client ever reaches
demo's expected 1224 definitions or stops at 1135 (which causes error 181).
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

COUNTER = 0x1988634
NET_STATE = 0x76446B0
UI_STATE = 0x84ABA50


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
    ap.add_argument("--seconds", type=float, default=40)
    ap.add_argument("--interval", type=float, default=0.2)
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
    peak = 0
    while time.time() - start < args.seconds:
        count = u32(COUNTER)
        net = u32(NET_STATE)
        ui = u32(UI_STATE)
        if count is not None:
            peak = max(peak, count)
        key = (count, net, ui)
        if key != last:
            last = key
            row = {"t": round(time.time() - start, 2), "weapon_count": count,
                   "net_state": net, "ui_state": ui}
            rows.append(row)
            print(json.dumps(row), flush=True)
        time.sleep(args.interval)
    summary = {"samples": len(rows), "peak": peak, "events": rows}
    print(json.dumps({"peak": peak, "samples": len(rows)}), flush=True)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(json.dumps(summary, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
