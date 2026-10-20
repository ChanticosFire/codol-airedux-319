"""Read and hexdump live client memory, following pointers if asked.

    python tools/peek.py 0xD5B12C            # dump 64 bytes at that address
    python tools/peek.py 0xD5B12C --len 128
    python tools/peek.py 0x36C7D7B8 --follow 2   # deref twice as a u32 chain
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


def dump(blob: bytes, base: int) -> None:
    for off in range(0, len(blob), 16):
        chunk = blob[off:off + 16]
        hx = " ".join(f"{b:02x}" for b in chunk)
        tx = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {base + off:#010x}  {hx:<48} {tx}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--len", type=int, default=64)
    parser.add_argument("--follow", type=int, default=0)
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()

    va = int(args.address, 16)
    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    try:
        for step in range(args.follow + 1):
            blob = read(h, va, args.len if step == args.follow else 4)
            if not blob:
                print(f"{va:#x}: unreadable")
                return 4
            if step == args.follow:
                print(f"=== {va:#x} ({len(blob)} bytes) ===")
                dump(blob, va)
            else:
                nxt = struct.unpack("<I", blob)[0]
                print(f"[{va:#x}] -> {nxt:#x}")
                va = nxt
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
