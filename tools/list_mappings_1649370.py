"""List the 1649370 client's mapped files (fastfiles, bsp, packs).

VirtualQueryEx walks the address space; every MEM_MAPPED region gets a name via
GetMappedFileNameW.  This answers whether mp_cross_fire's datafile/bsp is mapped
while the client sits in state 10.

Usage:
    python tools/list_mappings_1649370.py --filter mp_
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as W
import subprocess

k32 = C.WinDLL("kernel32", use_last_error=True)
psapi = C.WinDLL("psapi", use_last_error=True)

k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t]
k32.VirtualQueryEx.restype = C.c_size_t
k32.CloseHandle.argtypes = [W.HANDLE]
psapi.GetMappedFileNameW.argtypes = [W.HANDLE, C.c_void_p, W.LPWSTR, W.DWORD]
psapi.GetMappedFileNameW.restype = W.DWORD

EXE = "codol1649370-offline.exe"
MEM_MAPPED = 0x40000


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [
        ("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
        ("AllocationProtect", W.DWORD), ("PartitionId", W.WORD),
        ("RegionSize", C.c_size_t), ("State", W.DWORD),
        ("Protect", W.DWORD), ("Type", W.DWORD),
    ]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", default="", help="substring required in the mapped path")
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()
    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        print(f"OpenProcess failed: {C.get_last_error()}")
        return 3
    seen = set()
    rows = []
    address = 0
    limit = 0x80000000
    try:
        while address < limit:
            info = MEMORY_BASIC_INFORMATION()
            written = k32.VirtualQueryEx(handle, C.c_void_p(address), C.byref(info),
                                         C.sizeof(info))
            if not written:
                address += 0x1000
                continue
            size = int(info.RegionSize) or 0x1000
            if info.State == 0x1000 and info.Type == MEM_MAPPED:
                buf = C.create_unicode_buffer(512)
                if psapi.GetMappedFileNameW(handle, C.c_void_p(address), buf, len(buf)):
                    path = buf.value
                    if path not in seen and (not args.filter or args.filter.lower() in path.lower()):
                        seen.add(path)
                        rows.append((address, size, path))
            address += size
    finally:
        k32.CloseHandle(handle)
    rows.sort()
    print(f"client pid {pid}: {len(rows)} matching mapped files")
    for base, size, path in rows:
        print(f"{base:#010x} {size:#010x} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
