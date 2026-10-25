"""One-shot caller: hook a hot function and, on the very first entry only,
call 0x6398A0 (room.startgame) with ecx=1 from the client's own thread.

Why: sections 304/856/898 established that inject_call (CreateRemoteThread)
crashes this process no matter how small the target, while inline-hook caves
have been reliable since section 877.

The cave does:

    pushad
    cmp  dword [fired], 0
    jne  skip
    mov  dword [fired], 1
    mov  ecx, 1
    call 0x6398A0
    mov  [result], eax
    inc  dword [count]
skip:
    <replay stolen bytes>
    jmp back

Room slot semantics (section 898): [0x3306994] = [1, 3, 3], and
`cmp eax,1 / jle` sends slot 0 to the no-room branch while slots 1 and 2 take
the with-room branch that reaches 0x62F840 (the method that serialises a real
protocol message).

    python tools/call_startgame_1649370.py --pid N --target 0x621e50 --len 9
    python tools/call_startgame_1649370.py --pid N --restore --target 0x621e50 --len 9
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

STARTGAME = 0x6398A0
SLOT_BASE = 0xEC60000
SLOT_FIRED = SLOT_BASE
SLOT_RESULT = SLOT_BASE + 4
SLOT_COUNT = SLOT_BASE + 8

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--target", type=lambda v: int(v, 0), default=0x621E50)
    ap.add_argument("--len", type=int, default=9)
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

    if original[0] == 0xE9:
        raise SystemExit("target already hooked (starts with E9); restore first")

    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                           # pushad
    code += b"\x83\x3D" + struct.pack("<I", SLOT_FIRED) + b"\x00"   # cmp [fired],0
    code += b"\x75\x1B"                                       # jne +0x1B
    code += b"\xC7\x05" + struct.pack("<I", SLOT_FIRED) + b"\x01\x00\x00\x00"
    code += b"\xFF\x05" + struct.pack("<I", SLOT_COUNT)       # inc [count]
    code += b"\xB9\x01\x00\x00\x00"                           # mov ecx,1
    code += b"\xB8" + struct.pack("<I", STARTGAME)            # mov eax,STARTGAME
    code += b"\xFF\xD0"                                       # call eax
    code += b"\xA3" + struct.pack("<I", SLOT_RESULT)          # mov [result],eax
    code += b"\x61"                                           # popad
    code += original
    code += b"\xE9" + struct.pack("<i", (args.target + args.len) - (cave + len(code) + 5))

    if not write(cave, bytes(code)):
        raise SystemExit("cave write failed")
    patch = b"\xE9" + struct.pack("<i", cave - (args.target + 5))
    patch += b"\x90" * (args.len - len(patch))
    if not write(args.target, patch):
        raise SystemExit("patch failed")

    print(f"cave {cave:#x} installed; will call {STARTGAME:#x} with ecx=1 once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
