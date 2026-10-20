"""Find code that references a data address (default: onboard_character_selected).

find_calls.py resolves call rel32 targets; this looks for the plain 4-byte
little-endian address used by `push imm32` / `mov eax, imm32` style references,
which is how the game's stat name pointers appear.

    python tools/find_refs.py 0xDC3EA0
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
START = 0x400000
END = 0xDD0000
CHUNK = 0x100000


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
    import argparse
    ap = argparse.ArgumentParser(description="find imm32 references in the live client")
    ap.add_argument("target", nargs="?", default="0xDC3EA0")
    ap.add_argument("wait", nargs="?", type=int, default=30)
    ap.add_argument("--writes", action="store_true")
    ap.add_argument("--pattern", default=None)
    ns = ap.parse_args()
    target = int(ns.target, 16)
    wait = ns.wait
    raw = bytes.fromhex(ns.pattern) if ns.pattern else None
    write_only = ns.writes
    needle = raw if raw is not None else struct.pack("<I", target)
    write_needles = [b"\xc7\x05" + needle,          # mov dword [addr], imm32
                     b"\xc6\x05" + needle,          # mov byte [addr], imm8
                     b"\xff\x05" + needle,          # inc dword [addr]
                     b"\xff\x0d" + needle]          # dec dword [addr]
    write_only = "--writes" in sys.argv
    pid = find_pid()
    deadline = time.time() + wait
    while not pid and time.time() < deadline:
        time.sleep(1)
        pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 3
    print(f"pid={pid} looking for {target:#x} as imm32")
    hits = []
    writes = []
    try:
        base = START
        while base < END:
            data = read(h, base, CHUNK)
            if data:
                i = data.find(needle)
                while i >= 0:
                    hits.append(base + i)
                    i = data.find(needle, i + 1)
                for wn in write_needles:
                    j = data.find(wn)
                    while j >= 0:
                        writes.append((base + j, wn[:2].hex()))
                        j = data.find(wn, j + 1)
            base += CHUNK
    finally:
        k32.CloseHandle(h)
    if writes:
        print("write sites:")
        for va, op in writes:
            print(f"  {va:#010x}  opcode {op}")
    if not write_only and hits:
        for va in hits[:40]:
            print(f"ref at {va:#010x}")
        print(f"total {len(hits)} refs, {len(writes)} writes")
    else:
        print("no immediate references found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
