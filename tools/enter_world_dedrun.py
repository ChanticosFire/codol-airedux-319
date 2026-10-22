"""Call SV_ClientEnterWorld inside the 2697 dedrun process.

The 1649370 client stops at phase 8 and never sends clc_move, so the server
stays in CS_PRIMED and only sends empty snapshots.  SV_ClientEnterWorld is the
only path that sets client->gentity (via SV_GentityNum + ClientBegin) and
CS_ACTIVE, which makes SV_BuildClientSnapshot produce real snapshots.

    python tools/enter_world_dedrun.py --check
    python tools/enter_world_dedrun.py --call
"""
from __future__ import annotations

import argparse
import ctypes as C
import struct
import sys
import time
from ctypes import wintypes as W

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import read_dedrun_client as rr

SV_CLIENT_ENTER_WORLD = 0x4705F4
NAME_OFFSET = 0x2B8
STATE_OFFSET = 0x0
CS_PRIMED = 3
CS_ACTIVE = 4


def find_client(handle) -> tuple[int, int]:
    hits = rr.find_name(handle, b"AdministraClient\0")
    for hit in hits:
        client = hit - NAME_OFFSET
        state_raw = rr.read(handle, client, 4)
        if not state_raw:
            continue
        state = struct.unpack("<I", state_raw)[0]
        if state in (2, 3, 4):
            return client, state
    return 0, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--call", action="store_true")
    args = parser.parse_args()
    pid = rr.find_pid()
    if not pid:
        raise SystemExit("dedrun process not found")
    handle = rr.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit("OpenProcess failed")
    k32 = rr.k32
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                       C.POINTER(C.c_size_t)]
    k32.CreateRemoteThread.restype = W.HANDLE
    k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p,
                                       C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    try:
        client, state = find_client(handle)
        print("pid", pid, "client", hex(client) if client else None, "state", state)
        if not client:
            raise SystemExit("active client (CS_CONNECTED/PRIMED/ACTIVE) not found")
        if args.check or not args.call:
            return 0
        if state == CS_ACTIVE:
            print("already CS_ACTIVE, nothing to do")
            return 0
        shellcode = (b"\x6a\x00" + b"\x68" + struct.pack("<I", client)
                     + b"\xb8" + struct.pack("<I", SV_CLIENT_ENTER_WORLD)
                     + b"\xff\xd0" + b"\x83\xc4\x08" + b"\xc3")
        address = k32.VirtualAllocEx(handle, None, len(shellcode), 0x3000, 0x40)
        if not address:
            raise SystemExit(f"VirtualAllocEx failed {C.get_last_error()}")
        written = C.c_size_t()
        if not k32.WriteProcessMemory(handle, C.c_void_p(address), shellcode, len(shellcode),
                                      C.byref(written)):
            raise SystemExit(f"WriteProcessMemory failed {C.get_last_error()}")
        thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(address), None, 0, None)
        if not thread:
            raise SystemExit(f"CreateRemoteThread failed {C.get_last_error()}")
        k32.WaitForSingleObject(thread, 5000)
        k32.CloseHandle(thread)
        time.sleep(0.5)
        after = struct.unpack("<I", rr.read(handle, client + STATE_OFFSET, 4))[0]
        print("state_after", after, "expected", CS_ACTIVE)
        return 0
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
