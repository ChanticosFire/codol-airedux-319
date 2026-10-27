"""Write the live 1649370 playerState origin (diagnostic, one process only).

The snapshot stream rewrites the playerState every 100 ms, so this probe is
only meaningful after the game server has been stopped: then the client keeps
the last playerState and the camera follows whatever this writes.

    python tools/force_ps_origin_1649370.py --pid 1234 --origin 386,60,133.81
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
from ctypes import wintypes as W

CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
PS_BASE = 0x0C
ORIGIN_OFFSET = 0x30


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--origin", required=True, help="x,y,z floats")
    args = ap.parse_args()
    try:
        x, y, z = (float(part) for part in args.origin.split(","))
    except ValueError:
        raise SystemExit("origin must be three comma separated numbers")

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
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
        return buf.raw if got.value == size else None

    encoded = read(CL_PTR, 4)
    if not encoded:
        raise SystemExit("cl pointer unreadable")
    cl = struct.unpack("<I", encoded)[0] ^ CL_XOR
    ps = cl + PS_BASE
    target = ps + ORIGIN_OFFSET
    before = read(target, 12)
    payload = struct.pack("<fff", x, y, z)
    got = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(handle, ctypes.c_void_p(target),
                                ctypes.create_string_buffer(payload, 12), 12,
                                ctypes.byref(got))
    after = read(target, 12)
    report = {
        "pid": args.pid,
        "cl": hex(cl),
        "ps": hex(ps),
        "target": hex(target),
        "before": None if before is None else list(struct.unpack("<fff", before)),
        "after": None if after is None else list(struct.unpack("<fff", after)),
        "written": bool(ok) and got.value == 12,
    }
    print(json.dumps(report))
    k32.CloseHandle(handle)
    return 0 if report["written"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
