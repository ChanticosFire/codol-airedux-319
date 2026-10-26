"""Report which `ps` pointer the snapshot-decode hook actually sees.

The full weapon patch is stable but its writes never show up, so either the
`cl` global is not valid at `0x472406` or the field offsets are wrong.  This
tool separates the two: it installs a cave that only stores the computed
`ecx` into a scratch page, then the caller reads that page back and compares it
with the real `cl+0x0C`.

    python tools/probe_ps_pointer_1649370.py --pid 1234

It leaves the hook installed; pass --restore to undo.
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from ctypes import wintypes as W

TARGET = 0x472406
ORIGINAL = bytes.fromhex("8b55b483c40c")   # mov edx,[ebp-0x4c]; add esp,0xc (6 bytes)
CL_GLOBAL = 0x76638F4
CL_XOR = 0x6891D1C7

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p


def build_cave(cave: int, scratch: int, mode: str) -> bytes:
    code = bytearray()
    code += b"\x9c\x60"                                   # pushfd; pushad
    code += b"\xa1" + struct.pack("<I", CL_GLOBAL)        # mov eax,[cl global]
    code += b"\x35" + struct.pack("<I", CL_XOR)           # xor eax,mask -> cl
    if mode == "predicted":
        code += b"\x8d\x48\x0c"                           # lea ecx,[eax+0x0C]
    elif mode == "snapshot":
        code += b"\x8d\x48\x2c"                           # lea ecx,[eax+0x2C]
    else:
        code += b"\x8b\xc8"                               # mov ecx,eax  (cl itself)
    code += b"\x89\x0d" + struct.pack("<I", scratch)      # mov [scratch],ecx
    code += b"\x89\x05" + struct.pack("<I", scratch + 4)  # mov [scratch+4],eax (cl)
    code += b"\x61\x9d"                                   # popad; popfd
    code += ORIGINAL
    resume = TARGET + len(ORIGINAL)
    code += b"\xe9" + struct.pack("<i", resume - (cave + len(code) + 5))
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--mode", choices=("cl", "predicted", "snapshot"), default="predicted")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    h = kernel32.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit("OpenProcess failed")
    got = ctypes.c_size_t()

    def read(addr: int, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size,
                                          ctypes.byref(got)):
            raise SystemExit(f"read {addr:#x} failed")
        return buf.raw

    def write(addr: int, data: bytes) -> None:
        old = ctypes.c_ulong()
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), 0x40,
                                  ctypes.byref(old))
        kernel32.WriteProcessMemory(h, ctypes.c_void_p(addr),
                                    ctypes.create_string_buffer(data), len(data),
                                    ctypes.byref(got))
        kernel32.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), old.value,
                                  ctypes.byref(old))
        kernel32.FlushInstructionCache(h, ctypes.c_void_p(addr), len(data))

    if args.restore:
        write(TARGET, ORIGINAL)
        print(f"restored {TARGET:#x}")
        return 0

    if read(TARGET, len(ORIGINAL)) != ORIGINAL:
        raise SystemExit(f"unexpected bytes at {TARGET:#x}")

    scratch = int(kernel32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04) or 0)
    cave = int(kernel32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    if not scratch or not cave:
        raise SystemExit("VirtualAllocEx failed")
    write(cave, build_cave(cave, scratch, args.mode))
    write(TARGET, b"\xe9" + struct.pack("<i", cave - (TARGET + 5)) + b"\x90")
    print(f"mode={args.mode} scratch={scratch:#x} cave={cave:#x}")
    print(f"read back with: --scratch {scratch:#x}")
    # give the game a moment to run the hook
    import time
    time.sleep(2.0)
    raw = read(scratch, 8)
    seen_ps, seen_cl = (struct.unpack("<I", raw[:4])[0], struct.unpack("<I", raw[4:])[0])
    cl_now = struct.unpack("<I", read(CL_GLOBAL, 4))[0] ^ CL_XOR
    print(f"hook saw : ecx={seen_ps:#010x}  cl={seen_cl:#010x}")
    print(f"real cl  : {cl_now:#010x}")
    print(f"real ps  : predicted={cl_now + 0x0C:#010x}  snapshot={cl_now + 0x2C:#010x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
