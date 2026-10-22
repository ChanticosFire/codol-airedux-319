"""Find objects by vtable pointer in the running client.

The bdService task class uses vtable `0xD59A08`; scanning committed readable
memory for that dword finds every live task object, which tells us whether a
task still exists after a response and what state fields it holds.

    python tools/find_objects_by_vtable.py --vtable 0xd59a08 --dump 0x80
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
MEM_COMMIT = 0x1000
PAGE_READABLE = 0x02 | 0x04 | 0x20 | 0x40 | 0x80   # READONLY|READWRITE|EXECUTE*


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", C.c_uint32), ("__alignment1", C.c_uint32),
                ("RegionSize", C.c_size_t), ("State", C.c_uint32),
                ("Protect", C.c_uint32), ("Type", C.c_uint32), ("__alignment2", C.c_uint32)]


def iter_regions(handle):
    sc.k32.VirtualQueryEx.argtypes = [C.c_void_p, C.c_void_p,
                                      C.POINTER(MEMORY_BASIC_INFORMATION), C.c_size_t]
    sc.k32.VirtualQueryEx.restype = C.c_size_t
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    size = C.sizeof(mbi)
    while address < 0x7FFF0000:
        got = sc.k32.VirtualQueryEx(handle, C.c_void_p(address), C.byref(mbi), size)
        if not got:
            break
        base = int(mbi.BaseAddress or 0)
        region = int(mbi.RegionSize or 0)
        if not region:
            break
        if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in (0x02, 0x04, 0x20, 0x40, 0x80):
            yield base, region, int(mbi.Protect)
        address = base + region


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vtable", required=True, type=lambda v: int(v, 0))
    parser.add_argument("--dump", type=lambda v: int(v, 0), default=0x80)
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    pattern = struct.pack("<I", args.vtable)
    hits = []
    scanned = 0
    try:
        for base, size, protect in iter_regions(handle):
            blob = read(handle, base, size)
            scanned += len(blob)
            start = 0
            while True:
                index = blob.find(pattern, start)
                if index < 0:
                    break
                if index % 4 == 0:
                    address = base + index
                    hits.append({"address": hex(address),
                                 "bytes": read(handle, address, args.dump).hex()})
                start = index + 4
    finally:
        sc.k32.CloseHandle(handle)
    row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "vtable": hex(args.vtable), "scanned_bytes": scanned, "hits": hits}
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"vtable": row["vtable"], "scanned_bytes": scanned,
                      "hit_count": len(hits),
                      "addresses": [h["address"] for h in hits][:20]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
