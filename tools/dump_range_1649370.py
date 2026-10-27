"""Dump a raw memory range of a live client to a binary file (for diffs).

    python tools/dump_range_1649370.py --pid 1234 --addr 0x1c00000 --size 0x800000 --out runs/a.bin
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--addr", type=lambda text: int(text, 0), required=True)
    ap.add_argument("--size", type=lambda text: int(text, 0), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for {args.pid}")

    buf = ctypes.create_string_buffer(args.size)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(handle, ctypes.c_void_p(args.addr), buf, args.size,
                               ctypes.byref(got))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(buf.raw[:got.value] if ok or got.value else b"")
    print(f"{args.out} read={got.value}/{args.size} ok={bool(ok)}")
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
