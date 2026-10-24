"""Mark execution of 0x5BE7B4 (call 0xB7A6E0) by hooking it into a cave.

    0x5BE7B4  E8 xx xx xx xx   call 0xB7A6E0
    0x5BE7B9  ...              next instruction

The cave writes a sentinel into [0xE54BC48] (free scratch after we cleared the
duplicate-connect guard), calls the original target, then jumps back to
0x5BE7B9.  If the sentinel shows up we know the connect path reached this
instruction.

    python tools/mark_connect_check.py --pid N [--restore]
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
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]

TARGET = 0x5BE7B4          # call 0xB7A6E0
RETURN_TO = 0x5BE7B9       # original return address
CALLEE = 0xB7A6E0
SENTINEL_ADDR = 0xE54BC48
SENTINEL = 0xDEADBEEF
PATCH_LEN = 5


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
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(address: int, size: int) -> bytes:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
            return b""
        return buf.raw[:got.value]

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    original = read(TARGET, PATCH_LEN)
    if len(original) != PATCH_LEN or original[0] != 0xE8:
        print(json.dumps({"error": "target is not a call", "bytes": original.hex()}, indent=2))
        return 1

    if args.restore:
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(TARGET), PATCH_LEN, 0x40, C.byref(old))
        ok = write(TARGET, original)
        k32.VirtualProtectEx(handle, C.c_void_p(TARGET), PATCH_LEN, old.value, C.byref(old))
        print(json.dumps({"pid": pid, "restored": ok, "bytes": read(TARGET, PATCH_LEN).hex()}, indent=2))
        return 0 if ok else 1

    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = b"\x60"                                                # pushad
    code += b"\xC7\x05" + struct.pack("<I", SENTINEL_ADDR) + struct.pack("<I", SENTINEL)   # mov dword [addr], imm
    code += b"\x61"                                                # popad
    code += b"\xE8" + struct.pack("<I", (CALLEE - (cave + len(code) + 5)) & 0xFFFFFFFF)    # call callee
    code += b"\xE9" + struct.pack("<I", (RETURN_TO - (cave + len(code) + 5)) & 0xFFFFFFFF)  # jmp back
    if not write(cave, code):
        raise SystemExit("write cave failed")

    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(TARGET), PATCH_LEN, 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (TARGET + 5)) & 0xFFFFFFFF)
    ok = write(TARGET, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(TARGET), PATCH_LEN, old.value, C.byref(old))

    sentinel_now = struct.unpack("<I", read(SENTINEL_ADDR, 4))[0] if len(read(SENTINEL_ADDR, 4)) == 4 else None
    print(json.dumps({"pid": pid, "target": hex(TARGET), "cave": hex(cave), "patched": ok,
                      "sentinel_addr": hex(SENTINEL_ADDR), "sentinel_now": hex(sentinel_now or 0),
                      "original": original.hex()}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
