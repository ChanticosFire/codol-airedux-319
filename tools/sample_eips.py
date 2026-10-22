"""Sample thread instruction pointers of the running 1649370 client.

Repeatedly sampling every thread and printing the module-relative offsets shows
which function the engine is spinning in, which is how we locate where the map
load stalls after the zone bypass.

    python tools/sample_eips.py --seconds 6 --interval 0.5
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import time
from collections import Counter
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

K32 = sc.k32
K32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K32.OpenThread.restype = W.HANDLE
K32.SuspendThread.argtypes = [W.HANDLE]
K32.SuspendThread.restype = W.DWORD
K32.ResumeThread.argtypes = [W.HANDLE]
K32.ResumeThread.restype = W.DWORD
K32.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
K32.SetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
wow64_get = getattr(K32, "Wow64GetThreadContext", K32.GetThreadContext)
wow64_get.argtypes = [W.HANDLE, C.c_void_p]
K32.CloseHandle.argtypes = [W.HANDLE]
K32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
K32.CreateToolhelp32Snapshot.restype = W.HANDLE
K32.Thread32First.argtypes = [W.HANDLE, C.c_void_p]
K32.Thread32Next.argtypes = [W.HANDLE, C.c_void_p]


class THREADENTRY32(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ThreadID", W.DWORD),
                ("th32OwnerProcessID", W.DWORD), ("tpBasePri", W.LONG),
                ("tpDeltaPri", W.LONG), ("dwFlags", W.DWORD)]


def threads_of(pid: int):
    snap = K32.CreateToolhelp32Snapshot(0x4, pid)
    entry = THREADENTRY32()
    entry.dwSize = C.sizeof(THREADENTRY32)
    out = []
    if K32.Thread32First(snap, C.byref(entry)):
        while True:
            if entry.th32OwnerProcessID == pid:
                out.append(entry.th32ThreadID)
            if not K32.Thread32Next(snap, C.byref(entry)):
                break
    K32.CloseHandle(snap)
    return out


def sample(tid: int):
    handle = K32.OpenThread(0x0002 | 0x0008 | 0x0010, False, tid)
    if not handle:
        return None
    context_size, eip_offset = 716, 184
    storage = C.create_string_buffer(context_size + 16)
    aligned = (C.addressof(storage) + 15) & ~15
    C.memset(aligned, 0, context_size)
    C.c_uint32.from_address(aligned).value = 0x00010001
    eip = None
    if K32.SuspendThread(handle) != 0xFFFFFFFF:
        try:
            if wow64_get(handle, C.c_void_p(aligned)):
                eip = C.c_uint32.from_address(aligned + eip_offset).value
        finally:
            K32.ResumeThread(handle)
    K32.CloseHandle(handle)
    return eip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--base", type=lambda v: int(v, 0), default=0x400000)
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    rounds = []
    counts = Counter()
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        row = {}
        for tid in threads_of(pid):
            eip = sample(tid)
            if eip:
                row[tid] = hex(eip)
                counts[eip] += 1
        rounds.append(row)
        time.sleep(args.interval)
    top = [{"eip": hex(addr), "hits": hits, "offset": hex(addr - args.base)}
           for addr, hits in counts.most_common(12)]
    data = {"schema": 1, "build": 1649370, "pid": pid,
            "utc": datetime.now(timezone.utc).isoformat(),
            "samples": len(rounds), "top": top, "rounds": rounds[-6:]}
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
