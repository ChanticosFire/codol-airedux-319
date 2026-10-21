"""Start/send on the conn object created by 0xB82070."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD,
                                   C.POINTER(W.DWORD)]
k32.CreateRemoteThread.restype = W.HANDLE


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def u32(h, a):
    b = C.create_string_buffer(4)
    g = C.c_size_t()
    k32.ReadProcessMemory(h, C.c_void_p(a), b, 4, C.byref(g))
    return struct.unpack("<I", b.raw)[0]


def w(h, a, data):
    g = C.c_size_t()
    k32.WriteProcessMemory(h, C.c_void_p(a), C.create_string_buffer(data, len(data)), len(data), C.byref(g))


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    netobj = u32(h, 0x8269774)
    conn = u32(h, netobj + 0x4F4) if netobj else 0
    out = {"pid": p, "netobj": hex(netobj), "conn": hex(conn)}
    if not conn:
        print(json.dumps(out))
        return 1
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = (b"\x68" + struct.pack("<I", netobj + 0x500) +
            b"\xb9" + struct.pack("<I", conn) +
            b"\xe8" + struct.pack("<i", 0xBA4080 - (cave + 15)) + b"\xc3")
    w(h, cave, code)
    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    k32.WaitForSingleObject(th, 3000)
    time.sleep(2)
    out["after"] = {"c8": hex(u32(h, conn + 0xC8)), "644": hex(u32(h, conn + 0x644)),
                    "state": hex(u32(h, netobj + 0x4F8))}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
