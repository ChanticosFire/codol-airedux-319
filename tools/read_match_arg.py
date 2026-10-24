"""Wait for a MatchEntry breakpoint hit, then dump the three arguments it received.

    python tools/read_match_arg.py --events <run>/events.jsonl --seconds 60

The harness records the stack at 0xBA3BA0, so the caller return address and the
three arguments are at esp, esp+4, esp+8, esp+0xC.  This script resolves them
and dumps the pointed-to bytes so the match parameters become visible.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]


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
    ap.add_argument("--events", required=True)
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()
    path = Path(args.events)
    deadline = time.time() + args.seconds
    hit = None
    while time.time() < deadline:
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "MatchEntry" not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("milestone") == "MatchEntry":
                    hit = row
                    break
        if hit:
            break
        time.sleep(0.2)
    if not hit:
        print("no MatchEntry hit")
        return 2
    esp = int(hit["registers"]["esp"], 16)
    stack = bytes.fromhex(hit["stack"])
    ret, arg0, arg1, arg2 = struct.unpack_from("<4I", stack, 0)
    print(json.dumps({"return": hex(ret), "arg0": hex(arg0), "arg1": arg1, "arg2": arg2}, indent=2))
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def dump(address: int, size: int = 64) -> str:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return "<unreadable>"
        return buf.raw[:got.value].hex()

    for name, value in (("arg0", arg0), ("arg1", arg1), ("arg2", arg2)):
        if 0x10000 <= value < 0x7FFF0000:
            raw = dump(value)
            text = bytes.fromhex(raw).split(b"\0")[0][:40]
            print(f"{name} @{value:#x}: {raw[:64]}  ascii={text!r}")
        else:
            print(f"{name}: {value} (scalar)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
