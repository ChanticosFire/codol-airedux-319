"""Install an inline hook that performs the three missing session writes from
inside the client's own frame.

Sections 844-863 established that the inbound path is complete but dormant
because three writes never happen:

  1. [0x7508B80]  - the session/gamestate queue pointer - is never set (it is
     allocated statically in .data's 230 MB .bss region, so pointing at it is
     safe: section 849).
  2. [0x7887040]  - session event #1 - is created but never signalled.
  3. [0x7886E64]  - session event #2 - likewise.

This tool hooks a frequently-called function and has its cave perform all
three on every entry (the pointer write only when the slot is still null).
Because the cave runs on the client's own thread, it avoids the unreliable
CreateRemoteThread path (section 856).

    python tools/init_hook_1649370.py --pid N --target 0x5c05f0 --len 6
    python tools/init_hook_1649370.py --pid N --restore
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

QUEUE_PTR = 0x7508B80
QUEUE_OBJ = 0x8106A24
EVENT1 = 0x7887040
EVENT2 = 0x7886E64
SET_EVENT_THUNK = 0xCA816C          # IAT slot for kernel32!SetEvent
CL_PTR = 0x76638F4                  # encrypted CL pointer global
CL_XOR = 0x6891D1C7                 # CL pointer key
CL_GATE = 0x100260                  # offset of the inbound gate flag in CL
SLOT_BASE = 0xEC30000               # scratch for counters

SLOT_COUNT = SLOT_BASE
SLOT_QUEUE = SLOT_BASE + 4
SLOT_EV1 = SLOT_BASE + 8
SLOT_EV2 = SLOT_BASE + 0xC
SLOT_GATE = SLOT_BASE + 0x30
SLOT_RET = SLOT_BASE + 0x10

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--target", type=lambda v: int(v, 0), default=0x5C05F0)
    ap.add_argument("--len", type=int, default=6)
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    h = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    def read(va: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, size, ctypes.byref(n))
        return buf.raw if ok and n.value == size else None

    def write(va: int, blob: bytes) -> bool:
        old = W.DWORD()
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), 0x40, ctypes.byref(old))
        buf = ctypes.create_string_buffer(blob, len(blob))
        ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(blob),
                                    ctypes.byref(n))
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), old.value,
                             ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(va), len(blob))
        return bool(ok)

    original = read(args.target, args.len)
    if not original:
        raise SystemExit("cannot read target bytes")
    print(f"target {args.target:#x} original {original.hex()}")

    if args.restore:
        print("restore:", write(args.target, original))
        return 0

    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                     # pushad
    code += b"\xFF\x05" + struct.pack("<I", SLOT_COUNT)  # inc [count]

    # 1) point the queue global at the static session object, if still null
    code += b"\x83\x3D" + struct.pack("<I", QUEUE_PTR) + b"\x00"  # cmp [Q], 0
    code += b"\x75\x0A"                                          # jne +10
    code += b"\xC7\x05" + struct.pack("<I", QUEUE_PTR) + struct.pack("<I", QUEUE_OBJ)
    code += b"\xFF\x05" + struct.pack("<I", SLOT_QUEUE)

    # 2) SetEvent([EVENT1])
    code += b"\xA1" + struct.pack("<I", EVENT1)          # mov eax,[EVENT1]
    code += b"\x50"                                      # push eax
    code += b"\xFF\x15" + struct.pack("<I", SET_EVENT_THUNK)  # call [SetEvent]
    code += b"\xFF\x05" + struct.pack("<I", SLOT_EV1)

    # 3) SetEvent([EVENT2])
    code += b"\xA1" + struct.pack("<I", EVENT2)
    code += b"\x50"
    code += b"\xFF\x15" + struct.pack("<I", SET_EVENT_THUNK)
    code += b"\xFF\x05" + struct.pack("<I", SLOT_EV2)

    # 4) decrypt CL and enable the inbound gate: [CL+0x100260] = 1
    #    CL = [[0x76638F4] ^ 0x6891D1C7]
    code += b"\xA1" + struct.pack("<I", CL_PTR)          # mov eax,[0x76638F4]
    code += b"\x35" + struct.pack("<I", CL_XOR)          # xor eax,0x6891D1C7
    code += b"\x85\xC0"                                  # test eax,eax
    code += b"\x74\x14"                                  # je +0x14 (skip)
    code += b"\x83\xB8" + struct.pack("<I", CL_GATE) + b"\x00"   # cmp [eax+gate],0
    code += b"\x75\x0B"                                  # jne +0x0B (skip)
    code += b"\xC7\x80" + struct.pack("<I", CL_GATE) + b"\x01\x00\x00\x00"
    code += b"\xFF\x05" + struct.pack("<I", SLOT_GATE)
    # skip target lands here

    code += b"\x8B\x44\x24\x20"                          # mov eax,[esp+0x20] retaddr
    code += b"\xA3" + struct.pack("<I", SLOT_RET)
    code += b"\x61"                                      # popad

    code += original                                     # replay stolen bytes
    code += b"\xE9" + struct.pack("<i", (args.target + args.len) - (cave + len(code) + 5))

    if not write(cave, bytes(code)):
        raise SystemExit("cave write failed")
    patch = b"\xE9" + struct.pack("<i", cave - (args.target + 5))
    patch = patch + b"\x90" * (args.len - len(patch))
    if not write(args.target, patch):
        raise SystemExit("patch failed")

    print(f"cave {cave:#x} installed, {args.len} bytes patched")
    print(f"queue={QUEUE_PTR:#x} events={EVENT1:#x}/{EVENT2:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
