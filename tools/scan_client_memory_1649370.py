"""Scan a live 1649370 client for a 32-bit value (read-only).

The cgame side keeps its own copies of the playerState (predicted and snapshot)
and its own weapon registration array.  Writing marker words through the
snapshot wire lets us find those copies by value: every hit is a place the
client actually stored the word we sent.

    python tools/scan_client_memory_1649370.py --pid 1234 --value 0x12345678
    python tools/scan_client_memory_1649370.py --pid 1234 --value 0x2a392d4 --context 32

Nothing is written to the target process.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
from ctypes import wintypes as W

PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
MEM_COMMIT = 0x1000
CHUNK = 4 << 20


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", W.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", W.DWORD),
        ("Protect", W.DWORD),
        ("Type", W.DWORD),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--value", type=lambda text: int(text, 0), default=None)
    ap.add_argument("--ascii", default=None, help="search this ASCII string instead")
    ap.add_argument("--max-hits", type=int, default=200)
    ap.add_argument("--context", type=int, default=0,
                    help="dump this many bytes around each hit")
    ap.add_argument("--low", type=lambda text: int(text, 0), default=0x10000)
    ap.add_argument("--high", type=lambda text: int(text, 0), default=0x7FFF0000)
    args = ap.parse_args()
    if (args.value is None) == (args.ascii is None):
        raise SystemExit("give exactly one of --value or --ascii")

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(MBI), ctypes.c_size_t]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for pid {args.pid}")

    needle = (struct.pack("<I", args.value & 0xFFFFFFFF) if args.ascii is None
              else args.ascii.encode("ascii"))
    hits: list[int] = []
    regions = 0
    scanned = 0
    address = args.low
    while address < args.high and len(hits) < args.max_hits:
        mbi = MBI()
        got = k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                                 ctypes.sizeof(mbi))
        if not got:
            address += 0x1000
            continue
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0
        if size <= 0:
            address += 0x1000
            continue
        readable = (mbi.State == MEM_COMMIT
                    and not (mbi.Protect & PAGE_NOACCESS)
                    and not (mbi.Protect & PAGE_GUARD))
        if readable:
            regions += 1
            offset = 0
            while offset < size and len(hits) < args.max_hits:
                take = min(CHUNK, size - offset)
                buf = ctypes.create_string_buffer(take)
                read_got = ctypes.c_size_t()
                if k32.ReadProcessMemory(handle, ctypes.c_void_p(base + offset), buf,
                                         take, ctypes.byref(read_got)):
                    data = buf.raw[:read_got.value]
                    scanned += len(data)
                    start = 0
                    while len(hits) < args.max_hits:
                        index = data.find(needle, start)
                        if index < 0:
                            break
                        if index % 4 == 0 or args.ascii is not None:
                            hits.append((base + offset + index) & 0xFFFFFFFF)
                        start = index + 1
                offset += take
        address = base + size

    report = {
        "pid": args.pid,
        "needle": args.ascii if args.ascii is not None else hex(args.value),
        "regions": regions,
        "scanned_bytes": scanned,
        "hits": [hex(hit) for hit in hits],
        "hit_count": len(hits),
    }
    if args.context and hits:
        detail = []
        for hit in hits[:20]:
            buf = ctypes.create_string_buffer(args.context)
            read_got = ctypes.c_size_t()
            if k32.ReadProcessMemory(handle, ctypes.c_void_p(hit - args.context // 2), buf,
                                     args.context, ctypes.byref(read_got)):
                detail.append({"addr": hex(hit), "hex": buf.raw[:read_got.value].hex()})
        report["context"] = detail
    print(json.dumps(report, indent=1))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
