"""Scan Build 1649370's committed memory for a marker string.

Used to tell "the client never decoded our room listing" apart from "it decoded
the record but the UI filtered it": the listing record carries a distinctive
room name, so if that name exists in the client's heap the decode happened and
the field offsets around it can be inspected.

    python tools/scan_client_memory.py --ascii AI-Room --utf16 AI-Room
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
MEM_COMMIT = 0x1000
PAGE_READABLE = (0x02, 0x04, 0x20, 0x40, 0x80)  # READONLY, READWRITE, EXECUTE_*, WRITECOPY


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("RegionSize", C.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def regions(handle):
    query = sc.k32.VirtualQueryEx
    query.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(MEMORY_BASIC_INFORMATION), C.c_size_t]
    query.restype = C.c_size_t
    address = 0
    info = MEMORY_BASIC_INFORMATION()
    while address < 0x7FFF0000:
        if not query(handle, C.c_void_p(address), C.byref(info), C.sizeof(info)):
            break
        size = info.RegionSize or 0x1000
        if info.State == MEM_COMMIT and (info.Protect & 0xFF) in PAGE_READABLE:
            yield int(info.BaseAddress or address), size
        address = (info.BaseAddress or address) + size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ascii", default="AI-Room")
    parser.add_argument("--utf16", default="AI-Room")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--output")
    args = parser.parse_args()
    needles = [("ascii", args.ascii.encode("latin-1")),
               ("utf16", args.utf16.encode("utf-16-le"))]
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION | VM_READ
    if not handle:
        raise OSError("OpenProcess failed")
    hits: list[dict] = []
    scanned = 0
    try:
        for base, size in regions(handle):
            if size <= 0 or size > 64 * 1024 * 1024:
                continue
            buf = C.create_string_buffer(size)
            got = C.c_size_t()
            if not sc.k32.ReadProcessMemory(handle, C.c_void_p(base), buf, size, C.byref(got)):
                continue
            data = buf.raw[: got.value]
            scanned += len(data)
            for kind, needle in needles:
                start = 0
                while len(hits) < args.limit:
                    index = data.find(needle, start)
                    if index < 0:
                        break
                    hits.append({"kind": kind, "address": hex(base + index),
                                 "region": hex(base), "offset": index})
                    start = index + 1
                if len(hits) >= args.limit:
                    break
            if len(hits) >= args.limit:
                break
    finally:
        sc.k32.CloseHandle(handle)
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "needles": {kind: needle.decode("latin-1" if kind == "ascii" else "utf-16-le",
                                           "replace") for kind, needle in needles},
           "scanned_bytes": scanned, "hits": hits}
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(json.dumps(row, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
