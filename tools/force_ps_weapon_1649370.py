"""Keep forcing weapon fields into `predictedPlayerState` while the game runs.

The code cave at `0x472406` writes into a stack-local copy of the playerState,
so the predictor overwrites it every frame (§1213).  Rather than find
`CL_PredictMovement` first, this writes `cl->predictedPlayerState` from outside
at 100 Hz, which is fast enough to win most frames.  It answers one question:
does a correctly populated playerState make the client render a weapon at all?

    python tools/force_ps_weapon_1649370.py --pid 1234 --weapon 1 --seconds 15
    python tools/force_ps_weapon_1649370.py --pid 1234 --weapon 583

Fields written (offsets from the weapon index table and codol_weapon_bits.h):
  0x4C          word   current weapon
  0x55C + 4*n   dword  owned bitmap (only when weapon < 128)
  0x81C + w     byte   weaponmodels[weapon]
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

CL_GLOBAL = 0x76638F4
CL_XOR = 0x6891D1C7
PS_FROM_CL = 0x0C

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--weapon", type=int, default=1)
    ap.add_argument("--model", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--hz", type=float, default=100.0)
    ap.add_argument("--force-anim", action="store_true",
                    help="also force weapAnim/weaponstate/weaponTime")
    args = ap.parse_args()

    h = kernel32.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit("OpenProcess failed")
    got = ctypes.c_size_t()

    def read(addr: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size,
                                          ctypes.byref(got)):
            return None
        return buf.raw

    def write(addr: int, data: bytes) -> bool:
        return bool(kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr),
                                                ctypes.create_string_buffer(data),
                                                len(data), ctypes.byref(got)))

    cl_raw = read(CL_GLOBAL, 4)
    if not cl_raw:
        raise SystemExit("cannot read the cl global")
    cl = struct.unpack("<I", cl_raw)[0] ^ CL_XOR
    ps = cl + PS_FROM_CL
    print(f"cl={cl:#010x} ps={ps:#010x} weapon={args.weapon} model={args.model}")

    writes = 0
    deadline = time.monotonic() + args.seconds
    period = 1.0 / max(1.0, args.hz)
    while time.monotonic() < deadline:
        ok = True
        ok &= write(ps + 0x4C, struct.pack("<H", args.weapon & 0xFFFF))
        if args.weapon < 128:
            # The bitmap occupies four dwords at ps+0x55C.  Indices 64..95 map to
            # the *third* dword (ps+0x564), whose snapshot codec is plain 17, so
            # that range is actually writable from the server side too.
            word = args.weapon // 32
            bit = 1 << (args.weapon % 32)
            ok &= write(ps + 0x55C + 4 * word, struct.pack("<I", bit))
        ok &= write(ps + 0x81C + (args.weapon & 0x7FF),
                    bytes([args.model & 0xFF]))
        # weaponstate/weapAnim are what CG_AddViewWeapon normally gates on; with
        # no weapon object they stay 0 forever (§104), so try forcing them too.
        if args.force_anim:
            ok &= write(ps + 0x2BC, struct.pack("<I", 1))   # weapAnim = 1 (idle)
            ok &= write(ps + 0x2CC, struct.pack("<I", 0))   # weaponstate = 0 (ready)
            ok &= write(ps + 0x2C0, struct.pack("<I", 100))  # weaponTime
        if ok:
            writes += 1
        time.sleep(period)

    now = read(ps + 0x4C, 2)
    print(f"writes={writes} final weapon={struct.unpack('<H', now)[0] if now else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
