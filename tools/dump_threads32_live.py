"""Read 32-bit WOW64 thread contexts from the live client (no debugger attach)."""
from __future__ import annotations

import ctypes as C
import struct
import subprocess
import sys
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenThread.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.CloseHandle.argtypes = [W.HANDLE]


class THREADENTRY32(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ThreadID", W.DWORD),
                ("th32OwnerProcessID", W.DWORD), ("tpBasePri", C.c_long), ("tpDeltaPri", C.c_long),
                ("dwFlags", W.DWORD)]


k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.CreateToolhelp32Snapshot.restype = W.HANDLE
k32.Thread32First.argtypes = [W.HANDLE, C.POINTER(THREADENTRY32)]
k32.Thread32Next.argtypes = [W.HANDLE, C.POINTER(THREADENTRY32)]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) > 1 and p[1].isdigit():
            return int(p[1])
    raise SystemExit("client not running")


def read(h, va, n):
    b = C.create_string_buffer(n)
    g = C.c_size_t()
    if not k32.ReadProcessMemory(h, C.c_void_p(va), b, n, C.byref(g)):
        return None
    return b.raw


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    snap = k32.CreateToolhelp32Snapshot(0x4, 0)
    te = THREADENTRY32()
    te.dwSize = C.sizeof(te)
    ok = k32.Thread32First(snap, C.byref(te))
    wow = getattr(k32, "Wow64GetThreadContext", None)
    if not wow:
        print("no Wow64GetThreadContext")
        return 1
    wow.argtypes = [W.HANDLE, C.c_void_p]
    wow.restype = W.BOOL
    while ok:
        if te.th32OwnerProcessID == p:
            th = k32.OpenThread(0x0008 | 0x0040, False, te.th32ThreadID)  # GET_CONTEXT|QUERY
            if th:
                buf = C.create_string_buffer(716)
                C.c_uint32.from_address(C.addressof(buf)).value = 0x10007
                if wow(th, buf):
                    c = buf.raw
                    eip, esp, ebp, eax, ecx, edx = (struct.unpack_from("<I", c, o)[0]
                                                    for o in (184, 196, 180, 176, 172, 168))
                    print(f"\nTID {te.th32ThreadID} EIP={eip:08x} ESP={esp:08x} EBP={ebp:08x} "
                          f"EAX={eax:08x} ECX={ecx:08x} EDX={edx:08x}")
                    code = read(h, eip, 16)
                    print("  code:", code.hex() if code else "?")
                    st = read(h, esp, 64)
                    if st:
                        print("  stack:", " ".join(f"{v:08x}" for v in struct.unpack("<16I", st)))
                    ebp2 = ebp
                    for i in range(6):
                        fr = read(h, ebp2, 8)
                        if not fr:
                            break
                        nxt, ret = struct.unpack("<2I", fr)
                        print(f"  frame{i}: ret={ret:08x} ebp={ebp2:08x}")
                        if not nxt or nxt <= ebp2:
                            break
                        ebp2 = nxt
                k32.CloseHandle(th)
        ok = k32.Thread32Next(snap, C.byref(te))
    return 0


if __name__ == "__main__":
    sys.exit(main())
