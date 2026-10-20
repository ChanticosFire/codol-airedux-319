"""Force the frontend to activate once the client reaches dw=5.

Ported from codol-ember's launch319-reference orch319.py::install_ui_activate:

    install a one-shot trampoline at the per-frame pump 0x7F25F0 that calls
    0x5EBE10 (cppActivate) exactly once, then continues with the original six
    bytes.

Layout of the code cave:

    pushf; pushad
    cmp  byte [g2], 0
    jne  skip
    mov  byte [g2], 1
    call 0x5EBE10
skip:
    popad; popf
    <original 6 bytes>
    jmp  0x7F25F6

g2 is a guard byte at cave+0x800 so the activation only fires once; the caller
can reset it with --reset to re-trigger after a delay.

All work happens in the process; nothing is written to disk.
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
PUMP = 0x7F25F0          # per-frame pump entry
ACTIVATE = 0x5EBE10      # cppActivate
GUARD_OFFSET = 0x800


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


def install(h) -> int:
    """Install the trampoline; returns the cave address, or 0 on failure."""
    orig = read(h, PUMP, 6)
    if len(orig) != 6:
        print("cannot read pump entry", file=sys.stderr)
        return 0
    if orig[0] == 0xE9:
        rel = struct.unpack("<i", orig[1:5])[0]
        cave = PUMP + 5 + rel
        print(f"trampoline already installed, cave={cave:#x}")
        return cave
    cave = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE,
                              PAGE_EXECUTE_READWRITE)
    if not cave:
        print("VirtualAllocEx failed", ctypes.get_last_error(), file=sys.stderr)
        return 0
    cave = int(cave)
    guard = cave + GUARD_OFFSET
    code = bytearray(b"\x9c\x60")                                  # pushf; pushad
    code += b"\x80\x3d" + struct.pack("<I", guard) + b"\x00"       # cmp byte [guard],0
    code += b"\x75\x0c"                                            # jne skip
    code += b"\xc6\x05" + struct.pack("<I", guard) + b"\x01"       # mov byte [guard],1
    code += b"\xe8" + struct.pack("<i", ACTIVATE - (cave + len(code) + 5))
    code += b"\x61\x9d"                                            # popad; popf
    code += orig                                                   # original bytes
    code += b"\xe9" + struct.pack("<i", (PUMP + 6) - (cave + len(code) + 5))
    if not write(h, cave, bytes(code)):
        print("cave write failed", file=sys.stderr)
        return 0
    write(h, guard, b"\x00")
    if not write(h, PUMP, b"\xe9" + struct.pack("<i", cave - (PUMP + 5))):
        print("pump hook write failed", file=sys.stderr)
        return 0
    print(f"trampoline installed at {cave:#x} (activates {ACTIVATE:#x} once)")
    return cave


def reset_guard(h, cave: int) -> None:
    write(h, cave + GUARD_OFFSET, b"\x00")
    print("guard reset; activation will fire again")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true",
                        help="clear the one-shot guard so cppActivate runs again")
    parser.add_argument("--wait-dw5", type=int, default=0,
                        help="wait up to N seconds for dw==5 before installing")
    args = parser.parse_args()

    pid = find_pid()
    if not pid:
        print("client not running", file=sys.stderr)
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error(), file=sys.stderr)
        return 3
    print(f"pid={pid}")
    try:
        if args.wait_dw5:
            deadline = time.time() + args.wait_dw5
            while time.time() < deadline:
                data = read(h, 0x84ABA40, 4)
                if data and struct.unpack("<I", data)[0] == 5:
                    print("dw=5 reached")
                    break
                time.sleep(0.5)
            else:
                print("dw did not reach 5 in time", file=sys.stderr)
                return 4
        cave = install(h)
        if not cave:
            return 5
        if args.reset:
            reset_guard(h, cave)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
