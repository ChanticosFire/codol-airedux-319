"""Catch the exact moment net_state leaves 10 and grab a screenshot.

    python tools/watch_drop_1649370.py --seconds 120 --out runs/r717-drop.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

NET_STATE = 0x76446B0


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
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shot", default="runs/r717-drop.png")
    args = ap.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

    deadline = time.monotonic() + args.seconds
    pid = None
    start = time.monotonic()
    last = None
    history = []
    drop = None
    shot_done = False
    while time.monotonic() < deadline:
        if pid is None:
            pid = client_pid()
        if pid is None:
            time.sleep(0.2)
            continue
        handle = k32.OpenProcess(0x438, False, pid)
        if not handle:
            time.sleep(0.2)
            continue
        buf = ctypes.create_string_buffer(4)
        got = ctypes.c_size_t()
        if k32.ReadProcessMemory(handle, ctypes.c_void_p(NET_STATE), buf, 4, ctypes.byref(got)):
            state = struct.unpack("<I", buf.raw)[0]
            history.append({"t": round(time.monotonic() - start, 2), "net": state})
            if last == 10 and state != 10:
                drop = {"t": round(time.monotonic() - start, 2), "net": state}
                if not shot_done:
                    shot_done = True
                    subprocess.run(["python", "tools/capture_window_bg.py", "--out", args.shot],
                                   cwd=Path(__file__).resolve().parents[1],
                                   capture_output=True, text=True)
                break
            last = state
        k32.CloseHandle(handle)
        time.sleep(0.2)

    report = {"pid": pid, "drop": drop, "samples": len(history),
              "first": history[:5], "last": history[-5:], "shot": args.shot if shot_done else None}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pid", "drop", "samples", "shot")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
