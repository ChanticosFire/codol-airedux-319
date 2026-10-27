"""Find the memory address(es) of an exact ASCII string in a live client.

`scan_client_memory_1649370.py --ascii` matches prefixes, so `viewmodel_ak47`
also hits `viewmodel_ak47_drum_gl_reload`.  This tool resolves every hit to its
full string and keeps only the exact matches, which is what a reference scan
needs as its needle.

    python tools/find_exact_string_1649370.py --pid 1234 --text viewmodel_ak47
"""
from __future__ import annotations

import argparse
import ctypes
import json
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
    ap.add_argument("--text", required=True)
    ap.add_argument("--max-hits", type=int, default=2000)
    args = ap.parse_args()

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

    needle = args.text.encode("ascii")
    exact: list[str] = []
    total = 0
    address = 0x10000
    while address < 0x7FFF0000 and total < args.max_hits:
        mbi = MBI()
        if not k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                                  ctypes.sizeof(mbi)):
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
            offset = 0
            while offset < size and total < args.max_hits:
                take = min(CHUNK, size - offset)
                buf = ctypes.create_string_buffer(take)
                got = ctypes.c_size_t()
                if k32.ReadProcessMemory(handle, ctypes.c_void_p(base + offset), buf,
                                         take, ctypes.byref(got)):
                    data = buf.raw[:got.value]
                    start = 0
                    while total < args.max_hits:
                        index = data.find(needle, start)
                        if index < 0:
                            break
                        start = index + 1
                        total += 1
                        va = base + offset + index
                        head = ctypes.create_string_buffer(96)
                        read_got = ctypes.c_size_t()
                        if k32.ReadProcessMemory(handle, ctypes.c_void_p(va), head, 96,
                                                 ctypes.byref(read_got)):
                            text = head.raw[:read_got.value].split(b"\x00")[0]
                            if text == needle:
                                exact.append(hex(va))
                offset += take
        address = base + size

    print(json.dumps({"text": args.text, "raw_hits": total,
                      "exact_addresses": exact[:200]}, indent=1))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
