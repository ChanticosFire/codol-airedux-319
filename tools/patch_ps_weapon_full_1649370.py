"""Force the client's playerState to look like it owns a weapon.

`patch_ps_weapon_1649370.py` already installs a code cave at `0x472406` (right
after the playerState block is decoded) that writes `ps+0x4C = 1`.  That alone
is not enough to render a first-person weapon: the client also consults

  * `ps+0x55C` — owned-weapon bitmap (four dwords, bit N = weapon N owned)
  * `ps+0x81C` — one model byte per weapon

and neither of those travels in the snapshot, which is why a server-side grant
could never work (§1201, §1204: the bitmaps live in the playerState extension and
the client never reads `[reg+0x55C]` from a snapshot).  Writing them directly in
the client sidesteps that entirely.

    python tools/patch_ps_weapon_full_1649370.py --pid 1234
    python tools/patch_ps_weapon_full_1649370.py --pid 1234 --restore

The cave is built as: save flags/regs, write the three fields relative to the
decoded playerState, restore, then replay the two instructions we displaced.
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from ctypes import wintypes as W

TARGET = 0x472406
# 6 bytes, not 5: `mov edx,[ebp-0x4c]` (8b 55 b4) + `add esp,0xc` (83 c4 0c).
# The earlier 5-byte version left the 0x0c byte behind, so the jump landed
# mid-instruction -- that is what crashed every attempt, including --noop.
ORIGINAL = bytes.fromhex("8b55b483c40c")
PS_FROM_EBP = -0x3BB0                      # local snapshot + 0x20 = ps

# Weapon indices come from 他人文件参考/CODOL_3.19_武器索引表.xlsx:
#   0 = none, 1 = defaultweapon_mp (a placeholder with no model), 583 = m4_mp.
# 583 exceeds the 128-bit owned bitmap at ps+0x55C, but weaponmodels is one byte
# per weapon, so model[583] lives at ps+0x81C+583.  Override with --weapon.
WEAPON = 1          # ps+0x4C  (word)  weapon 1 = defaultweapon_mp (has a slot)
OWNED = 1 << WEAPON  # ps+0x55C bit N = weapon N owned; must agree with WEAPON
MODEL = 1           # ps+0x81C+WEAPON (byte)  weaponmodels[weapon]

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def build_cave(cave: int, noop: bool = False) -> bytes:
    code = bytearray()
    if not noop:
        code += b"\x9c\x60"                                    # pushfd; pushad
        # ecx = ps, derived from the fixed cl global instead of a guessed stack
        # offset: cl = *(0x76638F4) ^ 0x6891D1C7, ps = cl + 0x0C.
        code += b"\xa1" + struct.pack("<I", 0x76638F4)   # mov  eax,[0x76638F4]
        code += b"\x35" + struct.pack("<I", 0x6891D1C7)  # xor  eax,0x6891D1C7
                # 0x472406 decodes into cl->snapShot.ps, which patch_ps_commandtime
        # documents at cl+0x2C.  cl+0x0C is predictedPlayerState and gets
        # overwritten by the predictor every frame.
        code += b"\x8d\x48\x2c"                          # lea  ecx,[eax+0x2C]
        code += b"\x66\xc7\x41\x4c" + struct.pack("<H", WEAPON)  # mov word [ecx+0x4C], n
        code += b"\xc7\x81" + struct.pack("<I", 0x55C) + struct.pack("<I", OWNED)
        code += b"\xc6\x81" + struct.pack("<I", 0x81C + WEAPON) + bytes([MODEL & 0xFF])
        code += b"\x61\x9d"                                    # popad; popfd
    code += ORIGINAL
    resume = TARGET + len(ORIGINAL)
    code += b"\xe9" + struct.pack("<i", resume - (cave + len(code) + 5))
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--noop", action="store_true",
                    help="install a cave that only replays the displaced instructions")
    args = ap.parse_args()

    handle = kernel32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        print(f"OpenProcess failed: {ctypes.get_last_error()}", file=sys.stderr)
        return 1

    def read(addr: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size,
                                          ctypes.byref(got)) or got.value != size:
            raise OSError(f"read {addr:#x} failed")
        return buf.raw

    def write(addr: int, data: bytes) -> None:
        old = ctypes.c_ulong()
        if not kernel32.VirtualProtectEx(handle, ctypes.c_void_p(addr), len(data),
                                         0x40, ctypes.byref(old)):
            raise OSError(f"protect {addr:#x} failed")
        n = ctypes.c_size_t()
        ok = kernel32.WriteProcessMemory(handle, ctypes.c_void_p(addr), data, len(data),
                                         ctypes.byref(n))
        kernel32.VirtualProtectEx(handle, ctypes.c_void_p(addr), len(data), old.value,
                                  ctypes.byref(old))
        if not ok or n.value != len(data):
            raise OSError(f"write {addr:#x} failed")

    if args.restore:
        write(TARGET, ORIGINAL)
        print(f"restored {TARGET:#x} to {ORIGINAL.hex(' ')}")
        return 0

    current = read(TARGET, len(ORIGINAL))
    if current != ORIGINAL:
        print(f"unexpected bytes at {TARGET:#x}: {current.hex(' ')}", file=sys.stderr)
        return 1

    # Allocate a private executable page instead of reusing .text int3 padding:
    # patch_ps_commandtime_1649370.py does the same, and writing to .text pages
    # without FlushInstructionCache (or into a non-executable page) is why every
    # earlier attempt crashed -- even the --noop cave.
    cave = int(kernel32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        print("VirtualAllocEx failed", file=sys.stderr)
        return 1
    code = build_cave(cave, noop=args.noop)
    write(cave, code)
    entry = b"\xe9" + struct.pack("<i", cave - (TARGET + 5)) + b"\x90"
    write(TARGET, entry)
    kernel32.FlushInstructionCache(handle, ctypes.c_void_p(cave), len(code))
    kernel32.FlushInstructionCache(handle, ctypes.c_void_p(TARGET), 5)
    print(f"installed cave at {cave:#x} ({len(code)} bytes); "
          f"weapon={WEAPON} owned={OWNED:#x} model={MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
