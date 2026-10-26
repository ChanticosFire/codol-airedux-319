"""Find a 32-bit value inside a running client's address space (read-only).

Used to pin down where the client actually stores a playerState field: send a
snapshot whose field carries a distinctive bit pattern, then search for that
pattern.  This never writes to the target process.

    python tools/scan_client_value.py --pid 1234 --hex 0000a03e
    python tools/scan_client_value.py --pid 1234 --hex 0000a03e --limit 20
"""

from __future__ import annotations

import argparse
import ctypes
import json
from ctypes import wintypes as W

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = (0x02, 0x04, 0x08, 0x20, 0x40, 0x80)  # RO, RW, WC, EXEC_READ, EXEC_RW, EXEC_WC


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", W.DWORD),
        ("__alignment1", W.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", W.DWORD),
        ("Protect", W.DWORD),
        ("Type", W.DWORD),
        ("__alignment2", W.DWORD),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--hex", required=True, help="4-byte little-endian pattern, e.g. 0000a03e")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--max-mb", type=int, default=2048, help="stop after scanning this much")
    args = ap.parse_args()

    pattern = bytes.fromhex(args.hex)
    if not pattern:
        raise SystemExit("--hex must contain at least one byte")

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.VirtualQueryEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = k32.OpenProcess(0x410, False, args.pid)  # QUERY_INFORMATION | VM_READ
    if not handle:
        raise SystemExit(f"OpenProcess failed for pid {args.pid}")

    address = 0
    scanned = 0
    hits: list[dict] = []
    mbi = MEMORY_BASIC_INFORMATION64()
    try:
        while address < 0x7FFFFFFF and scanned < args.max_mb * 1024 * 1024:
            written = k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
            if not written:
                break
            base = mbi.BaseAddress
            size = mbi.RegionSize
            if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                    and not (mbi.Protect & PAGE_GUARD)):
                buf = ctypes.create_string_buffer(size)
                got = ctypes.c_size_t()
                ok = k32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, size, ctypes.byref(got))
                if ok and got.value:
                    data = buf.raw[:got.value]
                    scanned += len(data)
                    start = 0
                    while len(hits) < args.limit:
                        found = data.find(pattern, start)
                        if found < 0:
                            break
                        hits.append({"address": hex(base + found), "region": hex(base)})
                        start = found + 1
                    if len(hits) >= args.limit:
                        break
            address = base + size if size else address + 0x1000
    finally:
        k32.CloseHandle(handle)

    print(json.dumps({"pid": args.pid, "pattern": pattern.hex(), "scanned_bytes": scanned,
                      "hit_count": len(hits), "hits": hits}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
