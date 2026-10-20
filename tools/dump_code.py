"""Dump a code region from the running client and render a rough disassembly.

Uses capstone when available, otherwise prints bytes with ASCII context. The
goal is to read what 0x6BBF30 (firstlogin) does with the stat name pointer
0xDC3EA0, since that function decides whether the character screen appears.

    python tools/dump_code.py 0x6BBF30 0x200
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
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
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    va = int(sys.argv[1], 16)
    size = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x200
    wait = int(sys.argv[3]) if len(sys.argv) > 3 else 25

    pid = find_pid()
    deadline = time.time() + wait
    while not pid and time.time() < deadline:
        time.sleep(1)
        pid = find_pid()
    if not pid:
        print("client not running")
        return 3
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error())
        return 4
    try:
        data = read(h, va, size)
    finally:
        k32.CloseHandle(h)
    if not data:
        print("read failed")
        return 5

    print(f"pid={pid} {va:#x} ({len(data)} bytes)")
    try:
        import capstone  # type: ignore
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for insn in md.disasm(data, va):
            print(f"{insn.address:#010x}  {insn.bytes.hex(' '):<24} {insn.mnemonic} {insn.op_str}")
    except ImportError:
        for off in range(0, len(data), 16):
            chunk = data[off:off + 16]
            hexpart = " ".join(f"{b:02x}" for b in chunk)
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"{va + off:#010x}  {hexpart:<48} {text}")
        print("\n(install capstone for a real disassembly: pip install capstone)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
