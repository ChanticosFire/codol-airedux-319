"""Force playerState.weapon every snapshot by patching the client.

The decoder never writes `commandTime` when its changed bit is 0, so
`predictedPlayerState.commandTime` stays 0 and `CL_PredictMovement` treats every
server time as stale.  Rewriting the snapshot bit stream to carry the field broke
the byte cursor (§543), so this patch instead installs a code cave right after the
playerState block returns (`0x472406`) that copies `cl->serverTime` into
`cl->snapShot.ps.commandTime` (`cl+0x2C`).

    python tools/patch_ps_commandtime_1649370.py --pid 33668           # install
    python tools/patch_ps_commandtime_1649370.py --pid 33668 --restore # undo
"""
from __future__ import annotations

import argparse
import struct

import ctypes
from ctypes import wintypes as W

TARGET = 0x6701D6          # after "push ebp; mov ebp,esp; sub esp,0x28"
ORIGINAL = bytes.fromhex("a140f2e300")     # mov eax,[0xe3f240]  (stack cookie)
CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
SERVER_TIME = 0x3B90
PS_FROM_EBP = -0x3BB0        # local snapshot (ebp-0x3BD0) + 0x20 = ps
RESUME = TARGET + len(ORIGINAL)


def build_cave(cave: int) -> bytes:
    code = bytearray()
    code += b"\x9c\x60"                                   # pushfd; pushad
    code += b"\x8b\x45\x10"                              # mov eax,[ebp+0x10]  (ps base)
    code += b"\x66\xc7\x40\x4c\x01\x00"               # mov word ptr [eax+0x4C],1
    code += b"\x61\x9d"                                   # popad; popfd
    code += ORIGINAL
    code += b"\xe9" + struct.pack("<i", RESUME - (cave + len(code) + 5))
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit("OpenProcess failed")
    got = ctypes.c_size_t()

    def read(addr, size):
        buf = ctypes.create_string_buffer(size)
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            raise SystemExit(f"ReadProcessMemory({addr:#x}) failed")
        return buf.raw

    def write(addr, data):
        old = ctypes.c_ulong()
        k32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), 0x40, ctypes.byref(old))
        ok = k32.WriteProcessMemory(h, ctypes.c_void_p(addr), ctypes.create_string_buffer(data),
                                    len(data), ctypes.byref(got))
        k32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(addr), len(data))
        return bool(ok) and got.value == len(data)

    current = read(TARGET, len(ORIGINAL))
    if args.restore:
        if current != ORIGINAL and current[0] == 0xE9:
            ok = write(TARGET, ORIGINAL)
            print(f"restored={ok} bytes_after={read(TARGET, 5).hex()}")
            return 0
        print(f"nothing to restore (bytes={current.hex()})")
        return 0

    if current != ORIGINAL:
        raise SystemExit(f"unexpected bytes at {TARGET:#x}: {current.hex()}")
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")
    stub = build_cave(cave)
    if not write(cave, stub):
        raise SystemExit("cave write failed")
    entry = b"\xe9" + struct.pack("<i", cave - (TARGET + 5)) + b"\x90"
    if not write(TARGET, entry):
        raise SystemExit("entry write failed")
    print(f"pid={args.pid} target={TARGET:#x} cave={cave:#x} "
          f"entry={entry.hex()} stub={stub[:24].hex()}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
