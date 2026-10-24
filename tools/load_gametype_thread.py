"""Load the gametype fastfile by running 0x49E160 on a new remote thread.

    python tools/load_gametype_thread.py [--name common_gametype_mp]

The cave-based invoke_sequence cannot drive 0x49E160 (it needs the game's own
thread context).  This writes a tiny stub into the client and calls
CreateRemoteThread so 0x49E160 runs on a fresh thread with a normal stack:

    push mode ; push count ; push list ; call 0x49E160 ; xor eax,eax ; ret
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import sys
from ctypes import wintypes as W
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ring_bridge_1649370 import Client  # noqa: E402

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
k32.CreateRemoteThread.restype = W.HANDLE
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k32.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]

LOAD_FASTFILES = 0x49E160
ENTRY = 12


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="common_gametype_mp")
    ap.add_argument("--mode", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--wait-ms", type=int, default=8000)
    args = ap.parse_args()

    pid = args.pid
    if not pid:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                             capture_output=True, text=True, errors="replace").stdout
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[1].isdigit():
                pid = int(parts[1]); break
    if not pid:
        raise SystemExit("client not running")

    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    base = int(k32.VirtualAllocEx(handle, None, 0x3000, 0x3000, 0x40) or 0)
    if not base:
        raise SystemExit("VirtualAllocEx failed")

    names = [f"patch_{args.name}", args.name,
             f"patch_localized_{args.name}", f"localized_{args.name}"]

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    cursor = base + 0x800
    name_addr = []
    for text in names:
        name_addr.append(cursor)
        if not write(cursor, text.encode() + b"\0"):
            raise SystemExit("write name failed")
        cursor += 0x100

    list_addr = base + 0x400
    blob = struct.pack("<I", 4)
    for address in name_addr:
        blob += struct.pack("<III", address, 4, 0)
    if not write(list_addr, blob):
        raise SystemExit("write list failed")

    stub_addr = base
    rel = (LOAD_FASTFILES - (stub_addr + 20)) & 0xFFFFFFFF
    stub = (b"\x68" + struct.pack("<I", args.mode) +
            b"\x68" + struct.pack("<I", 4) +
            b"\x68" + struct.pack("<I", list_addr) +
            b"\xE8" + struct.pack("<I", rel) +
            b"\x31\xC0\xC3")
    if not write(stub_addr, stub):
        raise SystemExit("write stub failed")

    thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(stub_addr), None, 0, None)
    if not thread:
        raise SystemExit(f"CreateRemoteThread failed err={C.get_last_error()}")
    k32.WaitForSingleObject(thread, args.wait_ms)
    code = W.DWORD()
    k32.GetExitCodeThread(thread, C.byref(code))
    print(json.dumps({"pid": pid, "stub": hex(stub_addr), "list": hex(list_addr),
                      "names": names, "thread_exit": hex(code.value)},
                     ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
