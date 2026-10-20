"""Probe whether onboard_character_selected actually suppresses character select.

Earlier attempts wrote it after dw=5, by which point the character screen was
already on screen and the screenshot still showed it. This time write as soon
as the process appears, then capture at several moments to see whether the
screen is skipped at all.

Run this alongside a normal session (patch_runtime + servers). It only reads
and writes process memory.
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
k32.CreateRemoteThread.restype = ctypes.c_void_p
k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                   ctypes.c_void_p]
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
STAT_SETTER = 0x6B03D0
ONBOARDED = 0xDC3EA0
DW = 0x84ABA40
CS = 0x84ABA50


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


def call_stat(h, name_va: int) -> bool:
    cave = k32.VirtualAllocEx(h, None, 0x1000, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not cave:
        return False
    cave = int(cave)
    rel = STAT_SETTER - (cave + 5 + 5)
    code = (b"\xb8" + struct.pack("<I", name_va)
            + b"\xe8" + struct.pack("<i", rel) + b"\x33\xc0\xc3")
    if not write(h, cave, code):
        return False
    thread = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(cave), None, 0, None)
    if not thread:
        return False
    k32.WaitForSingleObject(ctypes.c_void_p(thread), 3000)
    k32.CloseHandle(ctypes.c_void_p(thread))
    return True


def main() -> int:
    print("waiting for client...", flush=True)
    pid = 0
    deadline = time.time() + 90
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            break
        time.sleep(0.3)
    if not pid:
        print("client never appeared", file=sys.stderr)
        return 2
    print(f"pid={pid} appeared, writing onboarded immediately", flush=True)
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed", ctypes.get_last_error(), file=sys.stderr)
        return 3
    try:
        ok = call_stat(h, ONBOARDED)
        print(f"stat setter call: {ok}", flush=True)
        # verify the stat name string is still intact and readable
        name = read(h, ONBOARDED, 28)
        print(f"stat name at {ONBOARDED:#x}: {name!r}", flush=True)
        start = time.time()
        last = None
        while time.time() - start < 70:
            dw = read(h, DW, 4)
            cs = read(h, CS, 4)
            state = (struct.unpack("<I", dw)[0] if len(dw) == 4 else None,
                     struct.unpack("<I", cs)[0] if len(cs) == 4 else None)
            if state != last:
                print(f"t+{time.time()-start:5.1f}s dw={state[0]} cs={state[1]}", flush=True)
                last = state
            time.sleep(0.5)
    finally:
        k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
