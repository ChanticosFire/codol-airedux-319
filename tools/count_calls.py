"""Count how often an arbitrary function start executes, without changing behaviour.

Replaces the first N bytes at a hook address with `jmp cave`, where the cave
increments a counter, replays the displaced original bytes verbatim, and jumps back
to hook+len(original). Registers and flags are preserved around the counter update, so
the instrumented function behaves exactly as before.

This exists because rounds 37, 38 and 48 all produced wrong conclusions from
measurement faults; a counting probe with a verifiable counter is the only kind of
observation that has held up.

    # count pump entry for 40 s
    python tools/count_calls.py --at 0xBAD800 --orig 558bec83e4f8 --secs 40

    # count the FE main loop
    python tools/count_calls.py --at 0x621753 --orig b824200000 --secs 40
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


def build_cave(cave: int, counter: int, original: bytes, resume: int) -> bytes:
    code = bytearray()
    code += b"\x9c"                                     # pushfd
    code += b"\x60"                                     # pushad
    code += b"\xff\x05" + struct.pack("<I", counter)    # inc dword [counter]
    code += b"\x61"                                     # popad
    code += b"\x9d"                                     # popfd
    code += original                                    # replay displaced bytes
    rel = resume - (cave + len(code) + 5)
    code += b"\xe9" + struct.pack("<i", rel)            # jmp back
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--at", required=True, help="hook address in hex, e.g. 0xBAD800")
    ap.add_argument("--orig", required=True, help="exact bytes at that address, hex")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--secs", type=float, default=30.0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    hook = int(args.at, 16)
    original = bytes.fromhex(args.orig)
    if len(original) < 5:
        print("need at least 5 displaced bytes to place a rel32 jump")
        return 2
    if len(original) > 16:
        print("too many displaced bytes")
        return 2
    resume = hook + len(original)

    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 3
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    label = args.label or f"{hook:#x}"
    try:
        live = read(h, hook, len(original))
        if live != original:
            print(f"byte mismatch at {hook:#x}: expected {original.hex()}, found {live.hex()}")
            return 4
        cave_addr = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE,
                                       PAGE_EXECUTE_READWRITE)
        if not cave_addr:
            print("VirtualAllocEx failed", ctypes.get_last_error())
            return 5
        cave = int(cave_addr)
        counter = cave + 0x200
        code = build_cave(cave, counter, original, resume)
        if not write(h, cave, code):
            print("cave write failed")
            return 6
        if not write(h, counter, b"\x00\x00\x00\x00"):
            print("counter init failed")
            return 6
        hook_code = b"\xe9" + struct.pack("<i", cave - (hook + 5))
        hook_code += b"\x90" * (len(original) - 5)
        if not write(h, hook, hook_code):
            print("hook write failed")
            return 6
        print(f"[{label}] hook {hook:#x} -> cave {cave:#x}, counter {counter:#x}")

        deadline = time.time() + args.secs
        last = 0
        while time.time() < deadline:
            raw = read(h, counter, 4)
            if len(raw) != 4:
                print(f"[{label}] counter unreadable - process gone?")
                return 7
            val = struct.unpack("<I", raw)[0]
            if val != last:
                print(f"[{label}] calls = {val}")
                last = val
            time.sleep(args.interval)
        print(f"[{label}] total after {args.secs:g}s = {last}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
