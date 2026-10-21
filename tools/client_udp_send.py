"""Send a raw getchallenge through the client's own 0xBB1420 sendto wrapper."""
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


def cave(h, code: bytes) -> int:
    addr = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    w = C.c_size_t()
    k32.WriteProcessMemory(h, C.c_void_p(addr), C.create_string_buffer(code, len(code)), len(code), C.byref(w))
    return addr


def run(h, addr: int) -> int:
    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, C.c_void_p(addr), None, 0, C.byref(tid))
    k32.WaitForSingleObject(th, 3000)
    time.sleep(0.3)
    code = W.DWORD()
    k32.GetExitCodeThread(th, C.byref(code))
    return code.value


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    w = k32.WriteProcessMemory
    ws = module_base(p, "ws2_32.dll")
    sock_rva = export_rva(r"C:\Windows\SysWOW64\ws2_32.dll", "socket")
    packet = b"\xff\xff\xff\xffgetchallenge 0 \"a731af49a6a2c7e2\""
    pkt = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04))
    w(h, C.c_void_p(pkt), C.create_string_buffer(packet, len(packet)), len(packet), C.byref(C.c_size_t()))
    # socket(AF_INET=2, SOCK_DGRAM=2, 0)
    c1 = cave(h, b"\x6a\x00\x6a\x02\x6a\x02\xe8" + struct.pack("<i", (ws + sock_rva) - 0) + b"\xc3")
    # relocate call
    c1 = cave(h, b"\x6a\x00\x6a\x02\x6a\x02\xe8" + struct.pack("<i", (ws + sock_rva) - (c1 + 11)) + b"\xc3")
    sock = run(h, c1)
    out = {"pid": p, "ws2_32": hex(ws), "socket": hex(sock), "packet_len": len(packet)}
    if sock in (0, 0xFFFFFFFF):
        print(json.dumps(out, indent=2))
        return 1
    # 0xBB1420(struct{socket,ip,...}, port, buf, len)
    c2 = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = bytearray()
    code += b"\x68" + struct.pack("<I", len(packet))       # len
    code += b"\x68" + struct.pack("<I", pkt)               # buf
    code += b"\x68" + struct.pack("<I", 28969)             # port (function calls htons)
    code += b"\x81\xec\x88\x00\x00\x00"                    # 0x88 struct
    code += b"\x89\x04\x24"                                # [esp]=socket
    code += b"\xc7\x44\x24\x04" + struct.pack("<I", 0x0100007F)  # [esp+4]=ip
    call_pos = len(code)
    code += b"\xe8\x00\x00\x00\x00"
    code += b"\x81\xc4\x94\x00\x00\x00"                    # add esp,0x94 (struct+3 args)
    code += b"\xc3"
    struct.pack_into("<i", code, call_pos + 1, 0xBB1420 - (c2 + call_pos + 5))
    w(h, C.c_void_p(c2), C.create_string_buffer(bytes(code), len(code)), len(code), C.byref(C.c_size_t()))
    rc = run(h, c2)
    out["send_return"] = rc
    Path("evidence/experiments/client-udp-send.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
