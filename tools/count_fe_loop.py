"""Count how often the FE main loop at 0x621750 actually runs.

Rounds 45 and 47 disagree about whether the pump runs every frame, and two earlier
"could not observe it" results were tool bugs. This uses the smallest possible
self-verifying probe: replace the 5-byte `mov eax,0x2024` at 0x621753 with a jump to
a code cave that increments a counter and then executes the original instruction.

    0x621750  push ebp
    0x621751  mov ebp, esp
    0x621753  B8 24 20 00 00   <- replaced with E9 <cave>
    0x621758  call 0xC43200

    cave:  pushfd / inc dword [counter] / popfd / mov eax,0x2024 / jmp 0x621758

The probe changes no register state and no control flow, so a count of zero means the
loop truly never runs, and a large count means it runs constantly.

    python tools/count_fe_loop.py --pid 1234 --cave 0x10000000 --counter 0x10000100
    python tools/count_fe_loop.py --read 0x10000100
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys

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
HOOK_AT = 0x621753          # the 5-byte `mov eax,0x2024`
RESUME_AT = 0x621758        # next instruction after it
COUNTER = 0x621750          # sentinel; real address comes from --counter

# NOTE the counter must live in writable memory. The .data region around 0x82E1400
# has been used for similar scratch before and is inside the image, but writing there
# needs no allocation. We default to a cave-adjacent slot instead.
DEFAULT_CAVE = 0x10000000
DEFAULT_COUNTER = 0x10000100


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


def install(h, cave: int, counter: int):
    original = read(h, HOOK_AT, 5)
    if original != b"\xb8\x24\x20\x00\x00":
        print(f"unexpected bytes at hook site: {original.hex()}")
        return None
    # Let the system choose the address: 0x10000000 and friends are frequently
    # taken inside a 32-bit game image.
    alloc = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not alloc:
        print("VirtualAllocEx failed", ctypes.get_last_error())
        return None
    cave = int(alloc)
    if not write(h, cave, b"\x00" * 4):
        pass
    counter = cave + 0x100
    print(f"allocated cave at {cave:#x}, counter at {counter:#x}")

    code = bytearray()
    code += b"\x9c"                                          # pushfd
    code += b"\xff\x05" + struct.pack("<I", counter)         # inc dword [counter]
    code += b"\x9d"                                          # popfd
    code += b"\xb8\x24\x20\x00\x00"                          # mov eax,0x2024
    jmp_back = RESUME_AT - (cave + len(code) + 5)
    code += b"\xe9" + struct.pack("<i", jmp_back)
    if not write(h, cave, bytes(code)):
        print("cave write failed")
        return None
    if not write(h, counter, b"\x00\x00\x00\x00"):
        print("counter init failed")
        return None
    hook = b"\xe9" + struct.pack("<i", cave - (HOOK_AT + 5))
    if not write(h, HOOK_AT, hook):
        print("hook write failed")
        return None
    print(f"probe installed: hook {HOOK_AT:#x} -> cave {cave:#x}, counter {counter:#x}")
    return (cave, counter)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--cave", default=hex(DEFAULT_CAVE))
    parser.add_argument("--counter", default=hex(DEFAULT_COUNTER))
    parser.add_argument("--read", help="just read this counter address and exit")
    parser.add_argument("--secs", type=float, default=0, help="install then watch N seconds")
    args = parser.parse_args()

    if args.read:
        pid = args.pid or find_pid()
        h = k32.OpenProcess(PROCESS_ALL, False, pid)
        if not h:
            print("OpenProcess failed")
            return 3
        try:
            val = struct.unpack("<I", read(h, int(args.read, 16), 4))[0]
            print(f"[{int(args.read, 16):#x}] = {val}")
        finally:
            k32.CloseHandle(h)
        return 0

    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    cave = int(args.cave, 16)
    counter = int(args.counter, 16)
    try:
        installed = install(h, cave, counter)
        if not installed:
            return 4
        cave, counter = installed   # install() re-allocates and moves the counter
        if args.secs:
            import time
            deadline = time.time() + args.secs
            last = None
            while time.time() < deadline:
                raw = read(h, counter, 4)
                if len(raw) != 4:
                    print("  counter unreadable (process gone?)")
                    break
                val = struct.unpack("<I", raw)[0]
                if val != last:
                    print(f"  counter = {val}")
                    last = val
                time.sleep(0.5)
            print(f"final counter = {last}")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
