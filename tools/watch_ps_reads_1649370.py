"""Watch which code reads a playerState field, using hardware breakpoints.

Static byte-pattern search cannot tell `[ps+0x4C]` apart from `[esp+0x4C]` or a
`+0x4C` jump displacement (§1217), so this drives one of the CPU's four debug
address registers instead: park a read breakpoint on `ps+offset`, let the game
run, and harvest the instruction pointer plus the faulting thread each time it
fires.

    python tools/watch_ps_reads_1649370.py --pid 1234 --field 0x4c --seconds 6
    python tools/watch_ps_reads_1649370.py --pid 1234 --field 0x15c

The breakpoint lives in the thread context, so every thread has to be stamped
with it; threads created afterwards are picked up by the second pass.
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

CL_GLOBAL = 0x76638F4
CL_XOR = 0x6891D1C7
PS_FROM_CL = 0x0C

# CONTEXT layout for x86 differs between Windows versions; these offsets are the
# ones matching the layout returned by GetThreadContext on this build.
CTX_DR0 = 0x04
CTX_DR1 = 0x08
CTX_DR2 = 0x0C
CTX_DR3 = 0x10
CTX_DR6 = 0x14
CTX_DR7 = 0x18
CTX_EFLAGS = 0x0C0
CTX_EIP = 0x0B8
CTX_SIZE = 0x2CC

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.OpenThread.restype = ctypes.c_void_p
kernel32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.GetThreadContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
kernel32.SetThreadContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--field", type=lambda v: int(v, 0), default=0x4C)
    ap.add_argument("--seconds", type=float, default=6.0)
    args = ap.parse_args()

    hp = kernel32.OpenProcess(0x1F0FFF, False, args.pid)
    if not hp:
        raise SystemExit("OpenProcess failed")
    got = ctypes.c_size_t()
    buf = ctypes.create_string_buffer(4)
    if not kernel32.ReadProcessMemory(hp, ctypes.c_void_p(CL_GLOBAL), buf, 4,
                                      ctypes.byref(got)):
        raise SystemExit("cannot read cl global")
    cl = struct.unpack("<I", buf.raw)[0] ^ CL_XOR
    watch = cl + PS_FROM_CL + args.field
    print(f"cl={cl:#010x} watching ps+{args.field:#x} = {watch:#010x}")

    # thread enumeration
    TH32CS_SNAPTHREAD = 0x4

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD),
                    ("th32ThreadID", W.DWORD), ("th32OwnerProcessID", W.DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", W.DWORD)]

    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]

    def threads() -> list[int]:
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if not snap or snap == ctypes.c_void_p(-1).value:
            return []
        out, te = [], THREADENTRY32()
        te.dwSize = ctypes.sizeof(THREADENTRY32)
        ok = kernel32.Thread32First(snap, ctypes.byref(te))
        while ok:
            if te.th32OwnerProcessID == args.pid:
                out.append(te.th32ThreadID)
            ok = kernel32.Thread32Next(snap, ctypes.byref(te))
        kernel32.CloseHandle(snap)
        return out

    # DR7: L0=1, RW0=11 (read/write), LEN0=11 (4 bytes)
    dr7 = 0x1 | (0x3 << 16) | (0x3 << 18)

    stamped = 0
    for tid in threads():
        ht = kernel32.OpenThread(0x1F03FF, False, tid)
        if not ht:
            continue
        ctx = ctypes.create_string_buffer(CTX_SIZE)
        struct.pack_into("<I", ctx, 0, 0x10017)  # + CONTEXT_DEBUG_REGISTERS(0x10)  # CONTEXT_FULL-ish flag
        kernel32.SuspendThread(ht)
        if kernel32.GetThreadContext(ht, ctx):
            struct.pack_into("<I", ctx, CTX_DR0, watch)
            struct.pack_into("<I", ctx, CTX_DR7, dr7)
            if kernel32.SetThreadContext(ht, ctx):
                stamped += 1
        kernel32.ResumeThread(ht)
        kernel32.CloseHandle(ht)
    print(f"threads stamped: {stamped}")

    seen: dict[int, int] = {}
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        for tid in threads():
            ht = kernel32.OpenThread(0x1F03FF, False, tid)
            if not ht:
                continue
            ctx = ctypes.create_string_buffer(CTX_SIZE)
            struct.pack_into("<I", ctx, 0, 0x10017)  # + CONTEXT_DEBUG_REGISTERS(0x10)
            kernel32.SuspendThread(ht)
            if kernel32.GetThreadContext(ht, ctx):
                dr6 = struct.unpack_from("<I", ctx, CTX_DR6)[0]
                if dr6 & 0xF:
                    eip = struct.unpack_from("<I", ctx, CTX_EIP)[0]
                    seen[eip] = seen.get(eip, 0) + 1
                    struct.pack_into("<I", ctx, CTX_DR6, 0)
                    struct.pack_into("<I", ctx, CTX_DR0, watch)
                    struct.pack_into("<I", ctx, CTX_DR7, dr7)
                    kernel32.SetThreadContext(ht, ctx)
            kernel32.ResumeThread(ht)
            kernel32.CloseHandle(ht)
        time.sleep(0.02)

    print(f"distinct eip hits: {len(seen)}")
    for eip, n in sorted(seen.items(), key=lambda kv: -kv[1])[:20]:
        print(f"   {eip:#010x}  x{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
