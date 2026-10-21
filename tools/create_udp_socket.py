"""Create a UDP socket in the client with ws2_32!socket(2,2,0) and store it at conn+0xC4."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

import pefile

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
k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.CreateToolhelp32Snapshot.restype = W.HANDLE
k32.Module32FirstW.argtypes = [W.HANDLE, C.c_void_p]
k32.Module32NextW.argtypes = [W.HANDLE, C.c_void_p]


class ME(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD),
                ("modBaseAddr", C.c_void_p), ("modBaseSize", W.DWORD), ("hModule", W.HMODULE),
                ("szModule", W.WCHAR * 256), ("szExePath", W.WCHAR * 260)]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def module_base(p: int, name: str) -> int:
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, p)
    e = ME(); e.dwSize = C.sizeof(e)
    base = 0
    if k32.Module32FirstW(snap, C.byref(e)):
        while True:
            if e.szModule.lower() == name.lower():
                base = e.modBaseAddr or 0
                break
            if not k32.Module32NextW(snap, C.byref(e)):
                break
    k32.CloseHandle(snap)
    return base


def export_rva(path: str, name: str) -> int:
    pe = pefile.PE(path, fast_load=False)
    for s in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if s.name and s.name.decode().lower() == name.lower():
            return s.address
    raise SystemExit(name)


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
    n = u32(h, 0x8269774)
    c = u32(h, n + 0x4F4) if n else 0
    ws = module_base(p, "ws2_32.dll")
    sock_fn = ws + export_rva(r"C:\Windows\SysWOW64\ws2_32.dll", "socket")
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = (b"\x6a\x00\x6a\x02\x6a\x02" +
            b"\xe8" + struct.pack("<i", sock_fn - (cave + 11)) + b"\xc3")
    w(h, cave, code)
    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    k32.WaitForSingleObject(th, 3000)
    code_out = W.DWORD()
    k32.GetExitCodeThread(th, C.byref(code_out))
    out = {"pid": p, "conn": hex(c), "socket_exit": code_out.value}
    if c and code_out.value not in (0, 0xFFFFFFFF):
        w(h, c + 0xC4, struct.pack("<I", code_out.value))
        out["stored_socket"] = hex(u32(h, c + 0xC4))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
