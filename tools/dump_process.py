"""Write a full-memory minidump of the client for offline stack inspection."""
from __future__ import annotations

import ctypes as C
import sys
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
dbg = C.WinDLL("dbghelp", use_last_error=True)

k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
k32.CreateFileW.restype = W.HANDLE
k32.CloseHandle.argtypes = [W.HANDLE]
dbg.MiniDumpWriteDump.argtypes = [W.HANDLE, W.DWORD, W.HANDLE, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p]
dbg.MiniDumpWriteDump.restype = W.BOOL


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: dump_process.py PID OUT.dmp")
        return 2
    pid = int(sys.argv[1])
    out = sys.argv[2]
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    if not h:
        print("OpenProcess failed", C.get_last_error())
        return 1
    f = k32.CreateFileW(out, 0x40000000, 0, None, 2, 0x80, None)
    if f in (None, -1):
        print("CreateFile failed", C.get_last_error())
        return 1
    # MiniDumpWithFullMemory | MiniDumpWithHandleData | MiniDumpWithThreadInfo
    ok = dbg.MiniDumpWriteDump(h, pid, f, 0x2 | 0x4 | 0x1000, None, None, None)
    print("dump", bool(ok), "error", C.get_last_error())
    k32.CloseHandle(f)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
