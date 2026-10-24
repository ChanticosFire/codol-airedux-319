"""Dump file names passed to the FS_OpenFile caller (0xC513D9) breakpoint hits.

    python tools/read_fs_names.py --events <run>/events.jsonl

Each hit records the stack and registers; the file name is the third argument of
the enclosing function, i.e. [ebp+0xC].  Resolving it tells us which fastfile the
demo playback asks for and where that name comes from.
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
    ap.add_argument("--limit", type=int, default=40)
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

    seen: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "FS" not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("milestone") not in ("FS", "FsOpen", "OpenFile", "FSOpen"):
            continue
        ebp = int(row["registers"].get("ebp", "0x0"), 16)
        if not (0x10000 <= ebp < 0x7FFF0000):
            continue
        pointer = u32(ebp + 0xC)
        if not pointer:
            continue
        name = cstr(pointer)
        if name not in seen:
            seen.append(name)
        if len(seen) >= args.limit:
            break
    print(json.dumps(seen, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
