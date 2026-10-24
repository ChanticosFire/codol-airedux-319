"""Hook a per-frame client function so 0x49E160 runs on the game's main thread.

    python tools/hook_load_gametype.py [--pid N] [--target 0x7EF0D0]

The cave does, once only:

    pushad
    cmp byte [flag], 1 ; jne skip
    push 0 ; push 4 ; push list ; call 0x49E160 ; add esp,12
    mov byte [flag], 1
skip:
    popad
    <replay the 5 overwritten bytes: push ebp / mov ebp,esp / sub esp,0x14>
    jmp 0x7EF0D5

Replaying from a cave is safe because popad restores esp before the originals run.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import sys
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]

PATCH_LEN = 5
DEFAULT_TARGET = 0x7EF0D0
DEFAULT_ORIGINAL = bytes.fromhex("558bec83ec14")  # push ebp / mov ebp,esp / sub esp,0x14
LOAD_FASTFILES = 0x49E160


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
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--target", type=lambda v: int(v, 0), default=DEFAULT_TARGET)
    ap.add_argument("--name", default="common_gametype_mp")
    args = ap.parse_args()
    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    base = int(k32.VirtualAllocEx(handle, None, 0x3000, 0x3000, 0x40) or 0)
    if not base:
        raise SystemExit("VirtualAllocEx failed")

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    names = [f"patch_{args.name}", args.name,
             f"patch_localized_{args.name}", f"localized_{args.name}"]
    cursor = base + 0x1800
    name_addr = []
    for text in names:
        name_addr.append(cursor)
        if not write(cursor, text.encode() + b"\0"):
            raise SystemExit("write name failed")
        cursor += 0x100

    list_addr = base + 0x1400
    blob = struct.pack("<I", 4)
    for address in name_addr:
        blob += struct.pack("<III", address, 4, 0)
    if not write(list_addr, blob):
        raise SystemExit("write list failed")

    flag_addr = base + 0x1F00
    if not write(flag_addr, b"\0"):
        raise SystemExit("write flag failed")

    cave = base
    replay = base + 0x100
    back = args.target + PATCH_LEN
    code = b""
    code += b"\x60"                                              # pushad
    code += b"\x80\x3D" + struct.pack("<I", flag_addr) + b"\x01"  # cmp byte [flag],1
    code += b"\x74" + bytes([0x14])                               # je skip
    code += b"\x6A\x00"                                           # push 0 (mode)
    code += b"\x6A\x04"                                           # push 4 (count)
    code += b"\x68" + struct.pack("<I", list_addr)                # push list
    code += b"\xE8" + struct.pack("<I", (LOAD_FASTFILES - (cave + len(code) + 5)) & 0xFFFFFFFF)
    code += b"\x83\xC4\x0C"                                       # add esp,12
    code += b"\xC6\x05" + struct.pack("<I", flag_addr) + b"\x01"  # mov byte [flag],1
    code += b"\x61"                                               # popad  (skip target)
    code += b"\xE9" + struct.pack("<I", (back - (cave + len(code) + 5)) & 0xFFFFFFFF)
    # skip lands here: popad + replay + jmp back
    skip_off = len(code)
    code += b"\x61"                                               # popad
    code += DEFAULT_ORIGINAL                                      # replay 5 bytes
    code += b"\xE9" + struct.pack("<I", (back - (cave + len(code) + 5)) & 0xFFFFFFFF)

    # fix je displacement to point at the popad block
    je_at = 4 + 6 + 2  # after pushad+cmp+je opcode
    disp = skip_off - (je_at + 2)
    code = code[:je_at + 1] + bytes([disp & 0xFF]) + code[je_at + 2:]

    if not write(cave, code):
        raise SystemExit("write cave failed")

    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(args.target), PATCH_LEN, 0x40, C.byref(old)):
        raise SystemExit("VirtualProtectEx failed")
    jump = b"\xE9" + struct.pack("<I", (cave - (args.target + 5)) & 0xFFFFFFFF)
    ok = write(args.target, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), PATCH_LEN, old.value, C.byref(old))
    print(json.dumps({"pid": pid, "target": hex(args.target), "cave": hex(cave),
                      "list": hex(list_addr), "flag": hex(flag_addr),
                      "patched": ok, "code_len": len(code)}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
