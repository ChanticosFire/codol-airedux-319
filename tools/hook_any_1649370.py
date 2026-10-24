"""Transparent runtime hook for an arbitrary function in CODOL 1649370.

This build reaches its network code through encrypted function pointers, so
static call graphs and pointer scans both come back empty.  Hooking the function
entry is the only reliable way to observe "was it called, from where, with what
arguments".

The stub is fully transparent:

    pushad
    mov  eax, [esp+0x20]      ; caller's return address (pushad moved esp by 32)
    mov  [slot_ret], eax
    mov  eax, [esp+0x24]      ; first stack argument
    mov  [slot_arg0], eax
    mov  eax, [esp+0x28]      ; second stack argument
    mov  [slot_arg1], eax
    inc  dword [slot_count]
    popad
    <replay the stolen prologue bytes>
    jmp  target+len

    python tools/hook_any_1649370.py --target 0x7F4F10 --probe
    python tools/hook_any_1649370.py --target 0x7F4F10
    python tools/hook_any_1649370.py --target 0x7F4F10 --read
    python tools/hook_any_1649370.py --target 0x7F4F10 --restore
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)

k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.VirtualProtectEx.restype = W.BOOL
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.FlushInstructionCache.restype = W.BOOL

SLOT_BASE = 0xE54BD00
SLOT_COUNT = SLOT_BASE
SLOT_RET = SLOT_BASE + 4
SLOT_ARG0 = SLOT_BASE + 8
SLOT_ARG1 = SLOT_BASE + 12


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--len", type=int, default=5)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, n: int) -> bytes | None:
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, n, C.byref(got)) or got.value != n:
            return None
        return buf.raw

    def u32(va: int) -> int | None:
        d = read(va, 4)
        return struct.unpack("<I", d)[0] if d else None

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    original = read(args.target, args.len)
    entry = read(args.target, 5)
    report: dict = {
        "pid": pid, "target": hex(args.target), "len": args.len,
        "original": original.hex() if original else None,
        "entry": entry.hex() if entry else None,
        "is_hooked": bool(entry and entry[0] == 0xE9),
        "counters": {"count": u32(SLOT_COUNT), "ret": u32(SLOT_RET),
                     "arg0": u32(SLOT_ARG0), "arg1": u32(SLOT_ARG1)},
    }
    for key in ("ret", "arg0", "arg1"):
        if isinstance(report["counters"].get(key), int):
            report["counters"][key] = hex(report["counters"][key])

    if args.probe or args.read:
        print(json.dumps(report, indent=2))
        return 0

    if args.restore:
        if not original:
            raise SystemExit("cannot read original bytes")
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(args.target), len(original), 0x40, C.byref(old))
        ok = write(args.target, original)
        k32.VirtualProtectEx(handle, C.c_void_p(args.target), len(original), old.value, C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(args.target), len(original))
        report.update(restored=ok, bytes_after=read(args.target, len(original)).hex())
        print(json.dumps(report, indent=2))
        return 0 if ok else 1

    if entry and entry[0] == 0xE9:
        print(json.dumps(dict(report, status="already_hooked"), indent=2))
        return 0
    if not original:
        raise SystemExit("cannot read original bytes")

    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                          # pushad
    code += b"\x8B\x44\x24\x20"                              # mov eax,[esp+0x20] ret
    code += b"\xA3" + struct.pack("<I", SLOT_RET)
    code += b"\x8B\x44\x24\x24"                              # mov eax,[esp+0x24] arg0
    code += b"\xA3" + struct.pack("<I", SLOT_ARG0)
    code += b"\x8B\x44\x24\x28"                              # mov eax,[esp+0x28] arg1
    code += b"\xA3" + struct.pack("<I", SLOT_ARG1)
    code += b"\xFF\x05" + struct.pack("<I", SLOT_COUNT)
    code += b"\x61"                                          # popad
    code += original                                         # replay stolen bytes
    rel = (args.target + args.len - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)                 # jmp target+len

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))

    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), args.len, 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (args.target + 5)) & 0xFFFFFFFF)
    jump += b"\x90" * (args.len - 5)
    hooked = write(args.target, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), args.len, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(args.target), args.len)

    for slot in (SLOT_COUNT, SLOT_RET, SLOT_ARG0, SLOT_ARG1):
        write(slot, b"\x00\x00\x00\x00")

    report.update(hooked=hooked, cave=hex(cave), code=bytes(code).hex(),
                  entry_after=read(args.target, args.len).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if hooked else 1


if __name__ == "__main__":
    raise SystemExit(main())
