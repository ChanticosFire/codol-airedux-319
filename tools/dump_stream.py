"""Dump the message stream that the client parses when a breakpoint hits.

    python tools/dump_stream.py --events <run>/events.jsonl --milestone GamestateParse --reg ecx --limit 3

The gamestate parser (0x472D80) receives the stream object in ecx:
  [ecx+0x14] = buffer pointer
  [ecx+0x18] = buffer length
  [ecx+0x1C] = cursor
This script reads those fields and dumps the buffered bytes, which is exactly
what the real server sent (recorded in the demo).
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
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
    ap.add_argument("--milestone", default="GamestateParse")
    ap.add_argument("--reg", default="ecx")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--output")
    args = ap.parse_args()
    path = Path(args.events)
    if not path.exists():
        print("no events")
        return 2
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int | None:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return None
        return struct.unpack("<I", buf.raw)[0]

    def read(address: int, size: int) -> bytes:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return b""
        return buf.raw[:got.value]

    dumps: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if args.milestone not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("milestone") != args.milestone:
            continue
        base = int((row.get("registers") or {}).get(args.reg, "0x0"), 16)
        if not (0x10000 <= base < 0x7FFF0000):
            continue
        buffer_ptr = u32(base + 0x14)
        length = u32(base + 0x18)
        cursor = u32(base + 0x1C)
        if not buffer_ptr or not length or length > 0x20000:
            continue
        blob = read(buffer_ptr, min(length, 0x2000))
        dumps.append({"stream": hex(base), "buffer": hex(buffer_ptr), "length": length,
                      "cursor": cursor, "hex": blob.hex()})
        if len(dumps) >= args.limit:
            break
    print(json.dumps(dumps, indent=1))
    if args.output:
        Path(args.output).write_text(json.dumps(dumps, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
