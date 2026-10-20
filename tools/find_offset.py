"""Find every instruction that references a structure offset as a disp32.

The 1F4 field sits at lobby+0x1F4, so its offset appears in code as the little-endian disp32 0xF4 0x01 0x00 0x00.
Our own writes to it are known to be conditional on obj1 status reaching 2, but if some other site writes it
under different conditions, the whole status-2 detour may be avoidable.

    python tools/find_offset.py 0x1F4
    python tools/find_offset.py 0x120 --lo 0xBB0000 --hi 0xBC0000
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"

MODRM_NAMES = {
    0x89: "mov [disp32], r32",
    0x8B: "mov r32, [disp32]",
    0x8D: "lea r32, [disp32]",
    0x39: "cmp [disp32], r32",
    0x3B: "cmp r32, [disp32]",
    0x3D: "cmp eax, imm32",
    0xC7: "mov dword [disp32], imm32",
    0xFF: "inc/dec/call/jmp [disp32]",
    0x81: "arith [disp32], imm32",
    0x83: "arith [disp32], imm8",
}


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("offset", help="structure offset in hex, e.g. 0x1F4")
    ap.add_argument("--lo", default="0x400000")
    ap.add_argument("--hi", default="0xDD0000")
    args = ap.parse_args()

    off = int(args.offset, 0)
    lo = int(args.lo, 0)
    hi = int(args.hi, 0)
    needle = struct.pack("<I", off)

    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 2
    try:
        data = read(h, lo, hi - lo)
        if not data:
            print("read failed")
            return 3
        print(f"scan {lo:#x}..{hi:#x} for disp32 {needle.hex()} (offset {off:#x})")
        hits = []
        i = data.find(needle)
        while i >= 0:
            hits.append(lo + i)
            i = data.find(needle, i + 1)
        print(f"  {len(hits)} raw hit(s)")
        for addr in hits:
            # the disp32 belongs to an instruction; show a few bytes before it
            start = max(lo, addr - 8)
            ctx = read(h, start, addr - start + 8)
            print(f"    disp at {addr:#08x}   ctx {ctx.hex()}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
