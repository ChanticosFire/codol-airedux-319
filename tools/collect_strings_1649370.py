"""Collect distinct ASCII strings containing a needle inside a live client.

Scanning for a byte pattern and printing raw hits is noisy when the same string
is referenced from many structures.  This tool resolves each hit to its full
NUL-terminated string and reports the de-duplicated set with a hit count, which
answers "which names of this family does the client actually hold in memory".

    python tools/collect_strings_1649370.py --pid 1234 --needle viewmodel_ --max-hits 400
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
    ap.add_argument("--needle", required=True)
    ap.add_argument("--max-hits", type=int, default=400)
    ap.add_argument("--low", type=lambda text: int(text, 0), default=0x10000)
    ap.add_argument("--high", type=lambda text: int(text, 0), default=0x7FFF0000)
    ap.add_argument("--out", default=None)
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

    needle = args.needle.encode("ascii")
    found: dict[str, int] = {}
    hits = 0
    address = args.low
    while address < args.high and hits < args.max_hits:
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
            while offset < size and hits < args.max_hits:
                take = min(CHUNK, size - offset)
                buf = ctypes.create_string_buffer(take)
                got = ctypes.c_size_t()
                if k32.ReadProcessMemory(handle, ctypes.c_void_p(base + offset), buf,
                                         take, ctypes.byref(got)):
                    data = buf.raw[:got.value]
                    start = 0
                    while hits < args.max_hits:
                        index = data.find(needle, start)
                        if index < 0:
                            break
                        start = index + 1
                        hits += 1
                        probe = ctypes.create_string_buffer(128)
                        read_got = ctypes.c_size_t()
                        va = base + offset + index
                        head = ctypes.create_string_buffer(64)
                        text = None
                        if k32.ReadProcessMemory(handle, ctypes.c_void_p(va), head, 64,
                                                 ctypes.byref(read_got)):
                            text = head.raw[:read_got.value].split(b"\x00")[0]
                        if text:
                            name = text.decode("latin-1", "replace")
                            found[name] = found.get(name, 0) + 1
                offset += take
        address = base + size

    report = {
        "pid": args.pid,
        "needle": args.needle,
        "raw_hits": hits,
        "distinct": len(found),
        "strings": [{"text": text, "hits": count}
                    for text, count in sorted(found.items(), key=lambda kv: -kv[1])],
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as out:
            out.write(text)
    print(text)
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
