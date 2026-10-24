"""Hook a per-frame function and call the queue processor (0x49F280) every frame.

    python tools/hook_queue_processor.py [--pid N] [--target 0x7EF0D0]

0x49F280 takes no arguments: it returns immediately when the queue count at
0x239B11C is zero, otherwise it walks 0x1D06440 and calls 0x49ED40 per entry.
That makes it safe to invoke from a hook, unlike 0x49E160.

Cave layout (52 bytes):
    pushad
    call 0x49F280
    popad
    <replay the 5 overwritten bytes: push ebp / mov ebp,esp / sub esp,0x14>
    jmp target+5

Inject a queue entry first (tools/inject_load_queue.py), then install this hook;
the loaded package registers its 88 gametype weapons into 0x1988B50.
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
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]

DEFAULT_TARGET = 0x7EF0D0
DEFAULT_ORIGINAL = bytes.fromhex("558bec83ec14")   # push ebp / mov ebp,esp / sub esp,0x14
PATCH_LEN = 5
QUEUE_PROC = 0x49F280


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
    args = ap.parse_args()
    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    back = args.target + PATCH_LEN
    code = b"\x60"                                                       # pushad
    rel = (QUEUE_PROC - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE8" + struct.pack("<I", rel)                             # call 0x49F280
    code += b"\x61"                                                      # popad
    code += DEFAULT_ORIGINAL                                             # replay 5 bytes
    code += b"\xE9" + struct.pack("<I", (back - (cave + len(code) + 5)) & 0xFFFFFFFF)
    if not write(cave, code):
        raise SystemExit("write cave failed")

    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(args.target), PATCH_LEN, 0x40, C.byref(old)):
        raise SystemExit("VirtualProtectEx failed")
    jump = b"\xE9" + struct.pack("<I", (cave - (args.target + 5)) & 0xFFFFFFFF)
    ok = write(args.target, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), PATCH_LEN, old.value, C.byref(old))
    print(json.dumps({"pid": pid, "target": hex(args.target), "cave": hex(cave),
                      "queue_proc": hex(QUEUE_PROC), "patched": ok,
                      "code_len": len(code)}, ensure_ascii=True, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
