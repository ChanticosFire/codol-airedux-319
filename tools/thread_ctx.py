"""Read a thread's Eip with a correctly laid-out x86 CONTEXT.

Round 37 shipped a 204-byte hand-rolled CONTEXT and produced meaningless results.
The real x86 CONTEXT is 716 bytes with this header:

    ContextFlags        0
    Dr0..Dr3, Dr6, Dr7  4..24
    FloatSave          28   (112 bytes -> ends 140)
    SegGs..SegDs      140..156
    Edi..Eax          156..180
    Ebp, Eip          180, 184
    SegCs, EFlags     188, 192
    Esp, SegSs        196, 200
    ExtendedRegisters 204   (512 bytes -> 716)

This module exposes read_eip() built on that layout, plus a self-check that fails
loudly if GetThreadContext does not fill the structure.

    python tools/thread_ctx.py            # self-check on the live client
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

THREAD_ALL = 0x1F03FF
CONTEXT_FULL = 0x00010007
EIP_OFFSET = 184
EBP_OFFSET = 180
ESP_OFFSET = 196
CONTEXT_SIZE = 716

EXE = "codomp_client_shipretail.exe"


class CONTEXT(ctypes.Structure):
    """x86 CONTEXT - exactly 716 bytes."""
    _fields_ = [
        ("ContextFlags", wt.DWORD),
        ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD), ("Dr3", wt.DWORD),
        ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
        ("FloatSave", ctypes.c_ubyte * 112),
        ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD), ("SegDs", wt.DWORD),
        ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD), ("Edx", wt.DWORD),
        ("Ecx", wt.DWORD), ("Eax", wt.DWORD),
        ("Ebp", wt.DWORD), ("Eip", wt.DWORD), ("SegCs", wt.DWORD), ("EFlags", wt.DWORD),
        ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
        ("ExtendedRegisters", ctypes.c_ubyte * 512),
    ]


assert ctypes.sizeof(CONTEXT) == CONTEXT_SIZE, (
    f"CONTEXT is {ctypes.sizeof(CONTEXT)} bytes, expected {CONTEXT_SIZE}")

k32.OpenThread.restype = wt.HANDLE
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
k32.GetThreadContext.restype = wt.BOOL
# This Python is 64-bit while the client is 32-bit (PE machine 0x14c), so the
# plain GetThreadContext returns success but fills nothing. Wow64GetThreadContext
# is the correct call for a WOW64 target and uses the same 716-byte layout.
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
k32.Wow64GetThreadContext.restype = wt.BOOL
k32.SuspendThread.argtypes = [wt.HANDLE]
k32.SuspendThread.restype = wt.DWORD
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.ResumeThread.restype = wt.DWORD
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ThreadID", wt.DWORD), ("th32OwnerProcessID", wt.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wt.DWORD)]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def thread_ids(pid: int) -> list[int]:
    snap = k32.CreateToolhelp32Snapshot(0x00000004, 0)
    ids: list[int] = []
    if not snap or snap == wt.HANDLE(-1).value:
        return ids
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(THREADENTRY32)
    k32.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
    k32.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
    ok = k32.Thread32First(snap, ctypes.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == pid:
            ids.append(entry.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return ids


def read_context(tid: int) -> CONTEXT | None:
    th = k32.OpenThread(THREAD_ALL, False, tid)
    if not th:
        return None
    suspended = False
    try:
        # A WOW64 target thread must be suspended before its context can be read
        # from a 64-bit host; without this both calls report success with zeros.
        if k32.SuspendThread(th) != 0xFFFFFFFF:
            suspended = True
        ctx = CONTEXT()
        ctx.ContextFlags = CONTEXT_FULL
        if not k32.Wow64GetThreadContext(th, ctypes.byref(ctx)):
            if not k32.GetThreadContext(th, ctypes.byref(ctx)):
                return None
        # sanity: Eip must look like a code address
        if not (0x400000 <= ctx.Eip < 0x10000000):
            return None
        return ctx
    finally:
        if suspended:
            k32.ResumeThread(th)
        k32.CloseHandle(th)


def main() -> int:
    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    tids = thread_ids(pid)
    print(f"pid={pid} threads={len(tids)} CONTEXT={ctypes.sizeof(CONTEXT)}B")
    good = 0
    for tid in tids:
        ctx = read_context(tid)
        if ctx is None:
            continue
        good += 1
        if good <= 5:
            print(f"  tid {tid}: Eip={ctx.Eip:#010x} Ebp={ctx.Ebp:#010x} Esp={ctx.Esp:#010x}")
    print(f"threads with a code-like Eip: {good}/{len(tids)}")
    if good == 0:
        print("SELF-CHECK FAILED: no thread produced a sane Eip", file=sys.stderr)
        return 3
    print("self-check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
