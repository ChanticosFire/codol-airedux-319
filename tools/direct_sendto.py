"""Call ws2_32!sendto directly with the conn socket and a raw getchallenge."""
from __future__ import annotations

import ctypes as C
import json
import socket
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

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
    sock = u32(h, c + 0xC4) if c else 0
    ws = module_base(p, "ws2_32.dll")
    sendto = ws + export_rva(r"C:\Windows\SysWOW64\ws2_32.dll", "sendto")
    packet = b"\xff\xff\xff\xffgetchallenge 0 \"a731af49a6a2c7e2\""
    pkt = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04))
    sa = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04))
    w(h, pkt, packet)
    w(h, sa, struct.pack("<HH4s8x", 2, socket.htons(28969), socket.inet_aton("127.0.0.1")))
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = bytearray()
    code += b"\x6a\x10"                          # tolen=16
    code += b"\x68" + struct.pack("<I", sa)      # to
    code += b"\x6a\x00"                          # flags=0
    code += b"\x68" + struct.pack("<I", len(packet))
    code += b"\x68" + struct.pack("<I", pkt)
    code += b"\x68" + struct.pack("<I", sock)
    call_pos = len(code)
    code += b"\xe8\x00\x00\x00\x00"
    code += b"\xc3"
    struct.pack_into("<i", code, call_pos + 1, sendto - (cave + call_pos + 5))
    w(h, cave, bytes(code))
    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    k32.WaitForSingleObject(th, 3000)
    code_out = W.DWORD()
    k32.GetExitCodeThread(th, C.byref(code_out))
    out = {"pid": p, "ws2_32": hex(ws), "sendto": hex(sendto), "socket": hex(sock),
           "sendto_return": code_out.value, "packet_len": len(packet)}
    Path("evidence/experiments/direct-sendto.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
