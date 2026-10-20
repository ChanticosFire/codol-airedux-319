"""Sample a register at a chosen address, without changing program behaviour.

count_calls.py only counts hits. This variant also stores the value of one register into a
readable slot each time the address executes, so the actual data flowing through a function
can be observed rather than inferred.

    cave:  pushfd / pushad
           mov [slot], <reg>
           inc dword [count]
           popad / popfd
           <replay displaced bytes>
           jmp back

The register is captured before the displaced instruction runs, so to observe the result of
a call, hook the instruction *after* the call.

    python tools/probe_reg.py --at 0xBB1716 --orig 8b55f08b4dfc --reg eax --secs 10
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40

k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                               wt.DWORD, wt.DWORD]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"

# register -> (push/pop already handled by pushad/popad, we just need the displacement into
# the saved register block on the stack is irrelevant because we read the live register)
REG_OFFSET_IN_PUSHAD = {
    "eax": 0x1C, "ecx": 0x18, "edx": 0x14, "ebx": 0x10,
    "esp": 0x0C, "ebp": 0x08, "esi": 0x04, "edi": 0x00,
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


def write(h, va: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data, len(data))
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def build_cave(cave: int, slot: int, count: int, reg: str, original: bytes,
               resume: int, ebp_offs: list[int] | None = None) -> bytes:
    code = bytearray()
    code += b"\x9c"                                     # pushfd
    code += b"\x60"                                     # pushad
    # with pushad the registers sit at esp+0..esp+0x1c; edi first, eax last
    off = REG_OFFSET_IN_PUSHAD[reg]
    code += b"\x8b\x44\x24" + bytes([off])              # mov eax,[esp+off]
    code += b"\xa3" + struct.pack("<I", slot)           # mov [slot],eax
    for k, ebp_off in enumerate(ebp_offs or []):
        # ebp sits at [esp+8] in the pushad block; load it, offset it, read through it
        code += b"\x8b\x44\x24\x08"                  # mov eax,[esp+8]
        if ebp_off:
            code += b"\x05" + struct.pack("<I", ebp_off)  # add eax, offset
        code += b"\x8b\x00"                            # mov eax,[eax]
        code += b"\xa3" + struct.pack("<I", slot + 4 + k * 4)  # mov [slot+4+k*4],eax
    code += b"\xff\x05" + struct.pack("<I", count)      # inc dword [count]
    code += b"\x61"                                     # popad
    code += b"\x9d"                                     # popfd
    code += original
    rel = resume - (cave + len(code) + 5)
    code += b"\xe9" + struct.pack("<i", rel)
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--at", required=True, help="hook address in hex")
    ap.add_argument("--orig", required=True, help="exact displaced bytes as hex")
    ap.add_argument("--reg", default="eax", choices=sorted(REG_OFFSET_IN_PUSHAD))
    ap.add_argument("--mem-ebp", action="append", default=[],
                    help="also sample [ebp+offset]; repeatable, e.g. --mem-ebp 0x88 --mem-ebp 0x90")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--secs", type=float, default=10.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    hook = int(args.at, 16)
    original = bytes.fromhex(args.orig)
    if not 5 <= len(original) <= 16:
        print("displaced bytes must be 5..16 long")
        return 2
    resume = hook + len(original)
    label = args.label or f"{hook:#x}"

    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 3
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    try:
        live = read(h, hook, len(original))
        if live != original:
            print(f"byte mismatch at {hook:#x}: want {original.hex()} got {live.hex()}")
            return 4
        cave_addr = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE,
                                       PAGE_EXECUTE_READWRITE)
        if not cave_addr:
            print("VirtualAllocEx failed")
            return 5
        cave = int(cave_addr)
        slot = cave + 0x100
        count = cave + 0x200
        ebp_offs = [int(x, 16) for x in args.mem_ebp]
        code = build_cave(cave, slot, count, args.reg, original, resume, ebp_offs)
        if not write(h, cave, code):
            print("cave write failed")
            return 6
        if not write(h, slot, b"\x00" * 32) or not write(h, count, b"\x00\x00\x00\x00"):
            print("slot init failed")
            return 6
        hook_code = b"\xe9" + struct.pack("<i", cave - (hook + 5))
        hook_code += b"\x90" * (len(original) - 5)
        if not write(h, hook, hook_code):
            print("hook write failed")
            return 6
        print(f"[{label}] hook {hook:#x} -> cave {cave:#x}  slot {slot:#x}  reg {args.reg}")

        deadline = time.time() + args.secs
        last_n = 0
        last_v = None
        while time.time() < deadline:
            raw_n = read(h, count, 4)
            raw_v = read(h, slot, 32)
            if len(raw_n) != 4 or len(raw_v) != 32:
                print(f"[{label}] unreadable - process gone?")
                return 7
            n = struct.unpack("<I", raw_n)[0]
            v = struct.unpack_from("<I", raw_v, 0)[0]
            extras = [struct.unpack_from("<I", raw_v, 4 + k * 4)[0]
                      for k in range(len(ebp_offs))]
            key = (n, v, tuple(extras))
            if key != last_v:
                msg = f"[{label}] n={n}  {args.reg}={v:#010x}"
                for off, val in zip(ebp_offs, extras):
                    msg += f"  [{off:#x}]={val:#010x}"
                print(msg)
                last_n, last_v = n, key
            time.sleep(args.interval)
        if last_v is None:
            print(f"[{label}] no hits")
        else:
            if isinstance(last_v, tuple):
                n_, v_ = last_v[0], last_v[1]
            else:
                n_, v_ = last_n, last_v
            print(f"[{label}] final n={n_}  {args.reg}={v_:#010x}  slots={last_v[2] if isinstance(last_v, tuple) and len(last_v) > 2 else None}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
