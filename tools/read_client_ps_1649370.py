"""Read the live 1649370 playerState out of a running client (read-only).

`ClientOriginReader` in `server1649370/gameserver.py` already established that

    cl  = *(0x76638F4) ^ 0x6891D1C7
    ps.origin 是 cl + 0x3C80   (三个 float)

and the playerState wire table puts origin at offset 0x30, so the playerState
base is `cl + 0x3C80 - 0x30 = cl + 0x3C50`.  Every field below is read as a
32-bit word at `ps + offset`, which is exactly what the snapshot descriptors
address.

This never writes to the client.

    python tools/read_client_ps_1649370.py --pid 1234
    python tools/read_client_ps_1649370.py --pid 1234 --watch 10 --interval 500
"""

from __future__ import annotations

import argparse
import ctypes
import json
import struct
import time
from ctypes import wintypes as W

CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
NET_STATE = 0x76446B0
PS_ORIGIN = 0x3C80
# Measured 2026-10-26 by marker search: the live playerState starts at
# cl + 0x0C, not at cl + 0x3C80 - 0x30. ps+0x170/ps+0x174 markers written by a
# snapshot were found at 0x13080cc0/0x13080cc4 with ps_base = 0x13080b50 and
# cl = 0x13080b44, and every field then read back exactly what the frame sent.
PS_BASE = 0x0C
COMMAND_NUMBER = 0x3B94

FIELDS = (
    ("commandTime", 0x0000, "i32"),
    ("pm_type", 0x0004, "u32"),
    ("pm_time", 0x0008, "i32"),
    ("bobCycle", 0x002C, "u32"),
    ("origin", 0x0030, "vec3"),
    ("weapon", 0x004C, "u32"),
    ("clientNum", 0x0158, "u32"),
    ("viewmodelIndex", 0x015C, "u32"),
    ("viewangles", 0x0160, "vec3"),
    ("viewHeightTarget", 0x016C, "i32"),
    ("groundEntityNum", 0x00C0, "u32"),
    ("gravity", 0x00A4, "u32"),
    ("speed", 0x00B0, "u32"),
    ("primary", 0x03F8, "u32"),
    ("altWeapon", 0x03FC, "u32"),
    ("fWeaponPosFrac", 0x0404, "f32"),
    ("clipWeapon", 0x0494, "u32"),
    ("clipCount", 0x0498, "u32"),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--watch", type=int, default=1, help="number of samples")
    ap.add_argument("--interval", type=int, default=500, help="milliseconds between samples")
    args = ap.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for pid {args.pid}")

    def read(addr: int, size: int):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        if got.value != size:
            return None
        return buf.raw

    def u32(addr: int):
        raw = read(addr, 4)
        return None if raw is None else struct.unpack("<I", raw)[0]

    try:
        for sample in range(max(1, args.watch)):
            if sample:
                time.sleep(max(0, args.interval) / 1000.0)
            row: dict = {"sample": sample, "pid": args.pid}
            net = u32(NET_STATE)
            row["net_state"] = net
            encoded = u32(CL_PTR)
            row["cl_encoded"] = None if encoded is None else hex(encoded)
            if not encoded:
                row["error"] = "cl pointer is null"
                print(json.dumps(row))
                continue
            cl = encoded ^ CL_XOR
            row["cl"] = hex(cl)
            row["command_number"] = u32(cl + COMMAND_NUMBER)
            ps = cl + PS_BASE
            row["ps"] = hex(ps)
            for name, offset, kind in FIELDS:
                if kind == "vec3":
                    raw = read(ps + offset, 12)
                    if raw is None:
                        row[name] = None
                    else:
                        row[name] = [round(v, 4) for v in struct.unpack("<fff", raw)]
                elif kind == "f32":
                    raw = read(ps + offset, 4)
                    row[name] = None if raw is None else round(struct.unpack("<f", raw)[0], 6)
                elif kind == "i32":
                    raw = read(ps + offset, 4)
                    row[name] = None if raw is None else struct.unpack("<i", raw)[0]
                else:
                    row[name] = u32(ps + offset)
            print(json.dumps(row))
    finally:
        k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
