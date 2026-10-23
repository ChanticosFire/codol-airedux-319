"""Read and poke the 1649370 client connection state (clc).

The client keeps its connection object at ``*(0x76638F4) ^ 0x6891D1C7``; the
frame code tests ``clc+0x3BE4`` to promote state 9 -> 10 after a successfully
parsed snapshot.  This tool exposes that field for diagnostics.

Usage:
    python tools/clc_1649370.py
    python tools/clc_1649370.py --set-be4 1
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as wt
import json
import struct
import subprocess

k32 = C.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, C.c_void_p, C.c_void_p,
                                  C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, C.c_void_p, C.c_void_p,
                                   C.c_size_t, C.POINTER(C.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codol1649370-offline.exe"
CLC_SLOT = 0x76638F4
CLC_XOR = 0x6891D1C7
STATE = 0x76446B0
STATE_STRIDE = 0x20
OFF_BE4 = 0x3BE4
OFF_STATE_TIME = 0x3B90


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
    buf = C.create_string_buffer(n)
    got = C.c_size_t()
    if not k32.ReadProcessMemory(h, C.c_void_p(va), buf, n, C.byref(got)):
        raise OSError(f"read {va:#x} failed: {C.get_last_error()}")
    return buf.raw[:got.value]


def write(h, va: int, blob: bytes) -> None:
    got = C.c_size_t()
    if not k32.WriteProcessMemory(h, C.c_void_p(va), C.create_string_buffer(blob, len(blob)),
                                  len(blob), C.byref(got)):
        raise OSError(f"write {va:#x} failed: {C.get_last_error()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--set-be4", type=lambda value: int(value, 0), default=None)
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print(f"OpenProcess failed: {C.get_last_error()}")
        return 3
    try:
        raw = struct.unpack("<I", read(h, CLC_SLOT, 4))[0]
        clc = raw ^ CLC_XOR
        before = struct.unpack("<I", read(h, clc + OFF_BE4, 4))[0]
        if args.set_be4 is not None:
            write(h, clc + OFF_BE4, struct.pack("<I", args.set_be4))
        after = struct.unpack("<I", read(h, clc + OFF_BE4, 4))[0]
        report = {
            "pid": pid, "clc_slot_raw": hex(raw), "clc": hex(clc),
            "be4_before": before, "be4_after": after,
            "states": [struct.unpack("<I", read(h, STATE + i * STATE_STRIDE, 4))[0]
                       for i in range(4)],
            "clc_time": struct.unpack("<I", read(h, clc + OFF_STATE_TIME, 4))[0],
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            from pathlib import Path
            Path(args.output).write_text(text, encoding="utf-8")
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
