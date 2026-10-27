"""Dump a range of a live 1649370 client's memory as hex dwords (read-only).

    python tools/read_client_memory_1649370.py --pid 1234 --addr 0x199d00 --size 0x200
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
from ctypes import wintypes as W

CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--addr", type=lambda text: int(text, 0), required=True)
    ap.add_argument("--size", type=lambda text: int(text, 0), default=0x100)
    ap.add_argument("--ps", action="store_true", help="address is relative to cl->ps")
    args = ap.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for pid {args.pid}")

    def read(addr: int, size: int):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size,
                                     ctypes.byref(got)):
            return None
        return buf.raw[:got.value]

    start = args.addr
    if args.ps:
        raw = read(CL_PTR, 4)
        cl = struct.unpack("<I", raw)[0] ^ CL_XOR
        start = cl + 0x0C + args.addr
    blob = read(start, args.size)
    if blob is None:
        raise SystemExit(f"unreadable at {start:#x}")
    rows = []
    for offset in range(0, len(blob) - 3, 4):
        word = struct.unpack_from("<I", blob, offset)[0]
        rows.append({"offset": hex(offset), "addr": hex(start + offset),
                     "word": hex(word), "int": word,
                     "float": round(struct.unpack_from("<f", blob, offset)[0], 5)})
    print(json.dumps({"start": hex(start), "size": len(blob), "rows": rows}, indent=1))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
