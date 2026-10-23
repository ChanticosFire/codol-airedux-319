"""Read the live 1649370 client configstring table and string pool.

Layout recovered from the client parser at 0x472D80:

    0xC86DD28  uint32 offsets[12761]   one pool offset per configstring slot
    0xC87A48C  char   pool[0x20000]    NUL terminated values
    0xC89A48C  uint32 pool_cursor      next free pool offset (starts at 1)
    0x77D8250  byte   slot_types[12761] expected asset type per slot (0xFF unset)

A slot whose offset is 0 resolves to ``pool[0]``, an empty string, which is
exactly what the map-loading check at 0x4549F0 sees when the slot was never
sent.

Usage:
    python tools/inspect_1649370_configstrings.py --output runs/cs.json
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as wt
import json
import struct
import subprocess
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, C.c_void_p, C.c_void_p,
                                  C.c_size_t, C.POINTER(C.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codol1649370-offline.exe"
OFFSETS = 0xC86DD28
POOL = 0xC87A48C
POOL_CURSOR = 0xC89A48C
TYPES = 0x77D8250
SLOT_COUNT = 0x31D9
POOL_LIMIT = 0x20000
INTERESTING = (0, 1, 2, 3, 4, 5, 6, 7, 8194)


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int) -> bytes:
    buf = C.create_string_buffer(n)
    got = C.c_size_t()
    if not k32.ReadProcessMemory(h, C.c_void_p(va), buf, n, C.byref(got)):
        return b""
    return buf.raw[:got.value]


def cstring(blob: bytes) -> str:
    return blob.split(b"\0", 1)[0].decode("latin-1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/1649370-configstrings.json"))
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--limit", type=int, default=64,
                        help="also report every nonzero slot below this index")
    args = parser.parse_args()
    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print(f"OpenProcess failed: {C.get_last_error()}")
        return 3
    try:
        cursor = struct.unpack("<I", read(h, POOL_CURSOR, 4))[0]
        table = read(h, OFFSETS, SLOT_COUNT * 4)
        types = read(h, TYPES, SLOT_COUNT)
        pool = read(h, POOL, POOL_LIMIT)
        rows = []
        for index in INTERESTING:
            offset = struct.unpack_from("<I", table, index * 4)[0]
            value = cstring(pool[offset:]) if 0 <= offset < len(pool) else None
            rows.append({"index": index, "type": types[index] if index < len(types) else None,
                         "offset": offset, "value": value})
        extra = []
        for index in range(min(args.limit, SLOT_COUNT)):
            offset = struct.unpack_from("<I", table, index * 4)[0]
            if offset:
                extra.append({"index": index,
                              "type": types[index] if index < len(types) else None,
                              "offset": offset,
                              "value": cstring(pool[offset:]) if offset < len(pool) else None})
        report = {"pid": pid, "pool_cursor": cursor, "pool_accessible": len(pool),
                  "interesting": rows, "nonzero_below_limit": extra}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
