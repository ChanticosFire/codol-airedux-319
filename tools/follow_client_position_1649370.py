"""Mirror the client's predicted origin back into the snapshot we send.

Why: the client only runs prediction while it holds a valid snapshot.  A static
snapshot pins the player to one spot every 100 ms, so held movement is undone.
Writing the client's own predicted origin into the snapshot's three floats makes
the server "confirm" the move, so prediction continues frame after frame.

The snapshot stores origin as three unaligned floats at 0x0F / 0x14 / 0x18 in
the order x / z / y (measured on build 1649370).

    python tools/follow_client_position_1649370.py --pid 30836 \
        --snapshot runs/snap-follow.bin --seconds 600
"""
from __future__ import annotations

import argparse
import struct
import time
from pathlib import Path

import ctypes
from ctypes import wintypes as W

CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
PS_ORIGIN = 0x3C80
SLOTS = ((0x0F, 0), (0x14, 2), (0x18, 1))  # (file offset, origin component)


def open_process(pid: int):
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = W.HANDLE
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    handle = k.OpenProcess(0x438, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for pid {pid}")
    return k, handle


def read_u32(k, handle, addr: int) -> int | None:
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0]


def read_origin(k, handle):
    enc = read_u32(k, handle, CL_PTR)
    if not enc:
        return None
    cl = enc ^ CL_XOR
    vals = []
    for index in range(3):
        word = read_u32(k, handle, cl + PS_ORIGIN + index * 4)
        if word is None:
            return None
        vals.append(struct.unpack("<f", struct.pack("<I", word))[0])
    return cl, tuple(vals)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--template", type=Path, default=None,
                        help="pristine snapshot copied to --snapshot at start")
    parser.add_argument("--hz", type=float, default=25.0)
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.template:
        args.snapshot.write_bytes(args.template.read_bytes())
    base = bytearray(args.snapshot.read_bytes())
    if len(base) < 0x1C:
        raise SystemExit("snapshot too small")

    k, handle = open_process(args.pid)
    period = 1.0 / max(1.0, args.hz)
    deadline = time.monotonic() + args.seconds
    last = None
    writes = 0
    while time.monotonic() < deadline:
        got = read_origin(k, handle)
        if got:
            cl, origin = got
            payload = bytearray(base)
            for off, comp in SLOTS:
                struct.pack_into("<f", payload, off, origin[comp])
            args.snapshot.write_bytes(payload)
            writes += 1
            if not args.quiet and (last is None or max(abs(a - b) for a, b in zip(origin, last)) > 0.05):
                last = origin
                print(f"cl={cl:#x} origin=({origin[0]:.3f},{origin[1]:.3f},{origin[2]:.3f}) writes={writes}", flush=True)
        time.sleep(period)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
