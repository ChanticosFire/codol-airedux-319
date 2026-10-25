"""Attach as a debugger and capture the real access-violation details.

Rounds 114-123 tried to deduce the faulting instruction statically; three separate
inferences were disproved by measurement.  Round 123 established the exit is a
genuine access violation (Com_Error was never called).  This script attaches to the
client with DebugActiveProcess and reports, for the first exception:

    ExceptionCode      -- e.g. 0xC0000005 = EXCEPTION_ACCESS_VIOLATION
    ExceptionAddress   -- the faulting EIP
    for AV: [0] = 0 read / 1 write / 8 execute, [1] = the address accessed
    the top of the stack (so we can see the return address)

Usage: python runs\_dbg_attach.py <pid> [seconds]
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

PID = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.DebugActiveProcess.argtypes = [W.DWORD]
k.DebugActiveProcess.restype = W.BOOL
k.DebugActiveProcessStop.argtypes = [W.DWORD]
k.WaitForDebugEvent.argtypes = [ctypes.c_void_p, W.DWORD]
k.WaitForDebugEvent.restype = W.BOOL
k.ContinueDebugEvent.argtypes = [W.DWORD, W.DWORD, W.DWORD]
k.ContinueDebugEvent.restype = W.BOOL
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

# DEBUG_EVENT is 96 bytes on x86; the exception record starts at offset 12.
BUF = 96
ev = ctypes.create_string_buffer(BUF)

EXC_NAMES = {
    0xC0000005: "EXCEPTION_ACCESS_VIOLATION",
    0xC000001D: "ILLEGAL_INSTRUCTION",
    0xC0000094: "INT_DIVIDE_BY_ZERO",
    0xC00000FD: "STACK_OVERFLOW",
    0xC0000409: "STACK_BUFFER_OVERRUN",
    0x80000003: "BREAKPOINT",
    0x80000004: "SINGLE_STEP",
    0x40010006: "OUTPUT_DEBUG_STRING",
    0xE06D7363: "CPP_EXCEPTION",
}

if not k.DebugActiveProcess(PID):
    raise SystemExit(f"DebugActiveProcess failed: {ctypes.get_last_error()}")

h = k.OpenProcess(0x438, False, PID)


def rd(addr, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), b, n, ctypes.byref(g)):
        return None
    return b.raw


print(f"attached to pid={PID}; waiting for exceptions...", flush=True)
t0 = time.monotonic()
reported = 0
while time.monotonic() - t0 < SECONDS:
    if not k.WaitForDebugEvent(ev, 500):
        continue
    raw = ev.raw
    code = struct.unpack_from("<I", raw, 0)[0]          # dwDebugEventCode
    pid = struct.unpack_from("<I", raw, 4)[0]
    tid = struct.unpack_from("<I", raw, 8)[0]
    if code == 1:  # EXCEPTION_DEBUG_EVENT
        exc_code = struct.unpack_from("<I", raw, 12)[0]
        exc_flags = struct.unpack_from("<I", raw, 16)[0]
        exc_addr = struct.unpack_from("<I", raw, 24)[0]
        nparams = struct.unpack_from("<I", raw, 28)[0]
        p0 = struct.unpack_from("<I", raw, 32)[0]
        p1 = struct.unpack_from("<I", raw, 36)[0]
        name = EXC_NAMES.get(exc_code, "?")
        print(f"\n*** EXCEPTION: {exc_code:#010x} ({name})", flush=True)
        print(f"    ExceptionAddress = {exc_addr:#010x}", flush=True)
        print(f"    flags={exc_flags} nparams={nparams} p0={p0} p1={p1:#010x}", flush=True)
        if exc_code == 0xC0000005:
            op = {0: "READ", 1: "WRITE", 8: "EXECUTE"}.get(p0, f"op{p0}")
            print(f"    access type = {op} at address {p1:#010x}", flush=True)
        # try a small stack dump via the thread context is complex; instead read
        # the bytes around EIP to identify the instruction
        dis = rd(exc_addr - 16, 40)
        if dis:
            print(f"    bytes around EIP: {dis.hex(' ')}", flush=True)
        reported += 1
        if reported >= 3:
            k.ContinueDebugEvent(pid, tid, 0x00010002)  # DBG_EXCEPTION_NOT_HANDLED
            break
    k.ContinueDebugEvent(pid, tid, 0x00010002)

k.DebugActiveProcessStop(PID)
print(f"\ndone, {reported} exception(s) reported", flush=True)
