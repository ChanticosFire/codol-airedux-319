"""Generic one-shot remote callback through an inline-hook cave.

Calls an arbitrary client function exactly once, on the client's own thread,
with a chosen ecx and one optional stack argument, then records its return value.

Why: inject_call (CreateRemoteThread) crashes this process every time it is
tried (sections 304/856/898), while inline-hook caves have been reliable since
section 877; section 900 proved the harness including trustworthy counters once
the scratch page is allocated per install.

    python tools/call_once_1649370.py --pid N --fn 0x639700 --ecx 1
    python tools/call_once_1649370.py --pid N --fn 0x6397c0 --arg 0
    python tools/call_once_1649370.py --pid N --restore
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

TARGET_DEFAULT = 0x621E50          # per-frame message handler, ~92k calls/window
LEN_DEFAULT = 9

SLOT_FIRED = 0
SLOT_RESULT = 4
SLOT_ESP = 8
SLOT_COUNT = 0x10

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def build_body(scratch: int, fn: int, ecx: int, arg: int | None, edi: int | None = None) -> bytes:
    """Build the guarded payload; jmp displacement computed after assembly."""
    parts: list[bytes] = []
    jmp_index = -1

    parts.append(b"\x83\x3D" + struct.pack("<I", scratch + SLOT_FIRED) + b"\x00")
    jmp_index = len(parts)
    parts.append(b"\x0F\x85\x00\x00\x00\x00")        # jne rel32 (patched)
    parts.append(b"\xC7\x05" + struct.pack("<I", scratch + SLOT_FIRED) + b"\x01\x00\x00\x00")
    parts.append(b"\xFF\x05" + struct.pack("<I", scratch + SLOT_COUNT))
    if edi is not None:
        parts.append(b"\xBF" + struct.pack("<I", edi & 0xFFFFFFFF))   # mov edi, EDI
    parts.append(b"\xB9" + struct.pack("<I", ecx & 0xFFFFFFFF))
    if arg is not None:
        parts.append(b"\x68" + struct.pack("<I", arg & 0xFFFFFFFF))
    parts.append(b"\xB8" + struct.pack("<I", fn & 0xFFFFFFFF))
    parts.append(b"\xFF\xD0")                        # call eax
    parts.append(b"\xA3" + struct.pack("<I", scratch + SLOT_RESULT))
    parts.append(b"\x89\x25" + struct.pack("<I", scratch + SLOT_ESP))
    if arg is not None:
        parts.append(b"\x83\xC4\x04")                # add esp,4 (cdecl cleanup)

    body = bytearray(b"".join(parts))
    # offset of the jne instruction within body
    jne_off = sum(len(p) for p in parts[:jmp_index])
    target = len(body)
    disp = target - (jne_off + 6)
    body[jne_off + 2:jne_off + 6] = struct.pack("<i", disp)
    return bytes(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--fn", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--ecx", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--edi", type=lambda v: int(v, 0), default=None)
    ap.add_argument("--arg", type=lambda v: int(v, 0), default=None)
    ap.add_argument("--target", type=lambda v: int(v, 0), default=TARGET_DEFAULT)
    ap.add_argument("--len", type=int, default=LEN_DEFAULT)
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

    if args.restore:
        print("restore:", write(args.target, original), "bytes:", original.hex())
        return 0

    if not args.fn:
        raise SystemExit("--fn is required (or use --restore)")
    print(f"target {args.target:#x} original {original.hex()}")
    if original[0] == 0xE9:
        raise SystemExit("target already hooked; restore first")

    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    scratch = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave or not scratch:
        raise SystemExit("VirtualAllocEx failed")

    body = build_body(scratch, args.fn, args.ecx, args.arg, args.edi)
    code = bytearray()
    code += b"\x60"                       # pushad
    code += body
    code += b"\x61"                       # popad
    code += original
    code += b"\xE9" + struct.pack("<i", (args.target + args.len) - (cave + len(code) + 5))

    if not write(cave, bytes(code)):
        raise SystemExit("cave write failed")
    patch = b"\xE9" + struct.pack("<i", cave - (args.target + 5))
    patch += b"\x90" * (args.len - len(patch))
    if not write(args.target, patch):
        raise SystemExit("patch failed")

    print(f"cave {cave:#x} scratch {scratch:#x}")
    print(f"will call {args.fn:#x} ecx={args.ecx:#x} edi={args.edi} arg={args.arg} once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
