"""Call the client's 0x5C0FD0 challengeResponse parser with a synthetic body."""
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
    text = b"challengeResponse 6ad8d973"
    buf = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04))
    w(h, buf, text + b"\x00")
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = (b"\xb8" + struct.pack("<I", buf) +
            b"\xe8" + struct.pack("<i", 0x5C0FD0 - (cave + 10)) + b"\xc3")
    w(h, cave, code)
    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    k32.WaitForSingleObject(th, 3000)
    time.sleep(1)
    n = u32(h, 0x8269774)
    c = u32(h, n + 0x4F4) if n else 0
    out = {"pid": p, "text": text.decode(), "buffer": hex(buf),
           "netobj": hex(n), "conn": hex(c), "c8": hex(u32(h, c + 0xC8)) if c else "0x0"}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
