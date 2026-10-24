"""Dump the client's weapon-string table (0x1988B50) to JSON.

    python tools/dump_weapon_table.py --output runs/weapon-table.json

The table size lives at 0x827F738 and the entries are char* at 0x1988B50 + i*4.
Running this while a demo plays captures the exact names the client registered
(1266 for the sample demo), which is the ground truth for the missing-weapons gap.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

TABLE = 0x1988B50
COUNT = 0x827F738


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
    ap.add_argument("--output", required=True)
    ap.add_argument("--limit", type=int, default=4000)
    args = ap.parse_args()
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
            return ""
        return buf.raw.split(b"\0")[0].decode("latin-1", "replace")

    count = u32(COUNT) or 0
    names = []
    for i in range(1, min(count, args.limit) + 1):
        entry = u32(TABLE + i * 4)
        pointer = u32(entry) if entry and 0x10000 <= entry < 0x7FFF0000 else None
        if pointer and 0x10000 <= pointer < 0x7FFF0000:
            text = cstr(pointer)
            if text:
                names.append(text)
    payload = {"count": count, "names": len(names), "entries": names}
    open(args.output, "w", encoding="utf-8").write(json.dumps(payload, indent=1, ensure_ascii=True) + "\n")
    print(json.dumps({"count": count, "names": len(names), "sample": names[:6]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
