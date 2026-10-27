"""Sample the live CODOL cbuf descriptor length (overflow probe).

The command buffer descriptor sits at 0x76595A4 as {pointer, capacity, length};
capacity is 0x20000 when the buffer is the native one.  "client command
overflow" means length ran away, so this probe logs the growth curve while a
session comes up.

    python tools/probe_cbuf_1649370.py --seconds 60
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

DESCRIPTOR = 0x76595A4


def client_pid() -> int | None:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "
         "'codol1649370-offline.exe' } | Select-Object -First 1).ProcessId"],
        capture_output=True, text=True)
    text = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
    return int(text) if text.isdigit() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    deadline = time.monotonic() + args.seconds
    pid = None
    while not pid and time.monotonic() < deadline:
        pid = client_pid()
        if not pid:
            time.sleep(0.2)
    if not pid:
        raise SystemExit("no client")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    handle = k32.OpenProcess(0x438, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed {pid}")
    rows = []
    peak = 0
    while time.monotonic() < deadline:
        buf = ctypes.create_string_buffer(12)
        got = ctypes.c_size_t()
        if k32.ReadProcessMemory(handle, ctypes.c_void_p(DESCRIPTOR), buf, 12,
                                 ctypes.byref(got)):
            pointer, capacity, length = struct.unpack("<3I", buf.raw)
            peak = max(peak, length)
            rows.append({"t": round(time.monotonic(), 2), "pointer": hex(pointer),
                         "capacity": capacity, "length": length})
        time.sleep(0.05)
    report = {"pid": pid, "samples": len(rows), "peak_length": peak,
              "last": rows[-1] if rows else None,
              "growth": [row for row in rows if row["length"]][:200]}
    text = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as out:
            out.write(text)
    print(json.dumps({"pid": pid, "samples": len(rows), "peak_length": peak,
                      "capacity": rows[-1]["capacity"] if rows else None,
                      "pointer": rows[-1]["pointer"] if rows else None}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
