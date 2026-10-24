"""Resolve the first argument of a breakpoint hit and print it as a string.

    python tools/read_call_arg.py --events <run>/events.jsonl --milestone LoadFastfile --frame ebp --offset 8

For cdecl/stdcall functions the first argument sits at [ebp+8]; for functions
where the breakpoint is at the very entry it may be at [esp+4].  This script
tries both and prints every distinct string it can resolve, so the caller's
argument becomes visible without another round trip.
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
    ap.add_argument("--milestone", default="")
    ap.add_argument("--contains", default="")
    ap.add_argument("--limit", type=int, default=30)
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

    def cstr(address: int, size: int = 128) -> str:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return "<unreadable>"
        return buf.raw.split(b"\0")[0].decode("latin-1", "replace")

    found: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if args.milestone and args.milestone not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if args.milestone and row.get("milestone") != args.milestone:
            continue
        regs = row.get("registers") or {}
        stack_hex = row.get("stack") or ""
        stack = bytes.fromhex(stack_hex) if stack_hex else b""
        candidates: list[tuple[str, int]] = []
        for name in ("ebp", "esp"):
            base = int(regs.get(name, "0x0"), 16)
            if not (0x10000 <= base < 0x7FFF0000):
                continue
            for offset in (8, 4, 0xC):
                value = u32(base + offset)
                if value and 0x10000 <= value < 0x7FFF0000:
                    candidates.append((f"{name}+{offset:#x}", value))
        for source, pointer in candidates:
            text = cstr(pointer)
            if args.contains and args.contains not in text:
                continue
            if not text or text == "<unreadable>":
                continue
            if any(row2["text"] == text for row2 in found):
                continue
            found.append({"source": source, "pointer": hex(pointer), "text": text})
        if len(found) >= args.limit:
            break
    print(json.dumps(found, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
