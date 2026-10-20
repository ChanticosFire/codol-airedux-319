"""Set one of the game's own stats by calling its stat setter.

Ported from codol-ember orch319.py::call_stat_set. 0x6B03D0 is the stat setter
and takes the stat-name pointer in EAX; 0xDC3EA0 is onboard_character_selected,
which is what makes the client skip character select and the keyboard prompt.

    python tools/stat_set.py --onboarded
    python tools/stat_set.py --name 0xDC3EA0
    python tools/stat_set.py --rank 70

--rank patches 0x50C330 (GetPlayerRank) so it returns a fixed zero-based rank,
which the UI shows as rank+1. The reference notes the number only refreshes
after cppActivate runs again.

Process memory only; nothing is written to disk.
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
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                               wt.DWORD, wt.DWORD]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CreateRemoteThread.restype = ctypes.c_void_p
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                   ctypes.c_void_p]
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
STAT_SETTER = 0x6B03D0
ONBOARDED = 0xDC3EA0
RANK_FN = 0x50C330


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def write(h, va: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data, len(data))
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def run_cave(h, code: bytes, timeout_ms: int = 3000) -> bool:
    cave = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not cave:
        print("VirtualAllocEx failed", ctypes.get_last_error(), file=sys.stderr)
        return False
    cave = int(cave)
    if not write(h, cave, code):
        print("cave write failed", file=sys.stderr)
        return False
    thread = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(cave), None, 0, None)
    if not thread:
        print("CreateRemoteThread failed", ctypes.get_last_error(), file=sys.stderr)
        return False
    k32.WaitForSingleObject(ctypes.c_void_p(thread), timeout_ms)
    k32.CloseHandle(ctypes.c_void_p(thread))
    return True


def set_stat(h, name_va: int) -> bool:
    """mov eax, name_va ; call stat_setter ; xor eax,eax ; ret"""
    call_at = 5
    cave = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not cave:
        print("VirtualAllocEx failed", ctypes.get_last_error(), file=sys.stderr)
        return False
    cave = int(cave)
    rel = STAT_SETTER - (cave + call_at + 5)
    code = (b"\xb8" + struct.pack("<I", name_va)
            + b"\xe8" + struct.pack("<i", rel)
            + b"\x33\xc0\xc3")
    if not write(h, cave, code):
        return False
    thread = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(cave), None, 0, None)
    if not thread:
        print("CreateRemoteThread failed", ctypes.get_last_error(), file=sys.stderr)
        return False
    k32.WaitForSingleObject(ctypes.c_void_p(thread), 3000)
    k32.CloseHandle(ctypes.c_void_p(thread))
    print(f"stat setter called with {name_va:#x}")
    return True


def patch_rank(h, rank: int) -> bool:
    """Make GetPlayerRank return a fixed value: `mov eax, imm32 ; ret`."""
    code = b"\xb8" + struct.pack("<I", rank & 0xFFFFFFFF) + b"\xc3"
    patched = (b"\xb8" + struct.pack("<I", rank & 0xFFFFFFFF) + b"\xc3").ljust(len(code), b"\x90")
    if not write(h, RANK_FN, patched):
        print("rank patch failed", file=sys.stderr)
        return False
    print(f"GetPlayerRank stubbed to return {rank} (UI level {rank + 1})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onboarded", action="store_true",
                        help="set onboard_character_selected (skips character/keyboard steps)")
    parser.add_argument("--name", type=lambda s: int(s, 0), default=None,
                        help="stat-name VA to pass to the stat setter")
    parser.add_argument("--rank", type=int, default=None,
                        help="stub GetPlayerRank to this zero-based rank")
    parser.add_argument("--wait", type=int, default=0,
                        help="seconds to wait for the client to appear")
    args = parser.parse_args()

    deadline = time.time() + max(args.wait, 0)
    pid = find_pid()
    while not pid and time.time() < deadline:
        time.sleep(1)
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
        if args.onboarded:
            set_stat(h, ONBOARDED)
        if args.name is not None:
            set_stat(h, args.name)
        if args.rank is not None:
            patch_rank(h, args.rank)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
