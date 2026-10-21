"""Create and start a conn object in the community offline client.

Calls the real conn constructor 0xBA2800 (size 0xAE8) and the start routine
0xBA4080 with the netadr at netobj+0x500, then reports the resulting state.
"""
from __future__ import annotations

import ctypes as C
import json
import socket
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

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


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("community client not running")


def u32(h, a: int) -> int:
    buf = C.create_string_buffer(4)
    got = C.c_size_t()
    k32.ReadProcessMemory(h, C.c_void_p(a), buf, 4, C.byref(got))
    return struct.unpack("<I", buf.raw)[0]


def w(h, a: int, data: bytes):
    wrote = C.c_size_t()
    k32.WriteProcessMemory(h, C.c_void_p(a), C.create_string_buffer(data, len(data)), len(data),
                           C.byref(wrote))


def cave(h, code: bytes) -> int:
    addr = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    w(h, addr, code)
    tid = W.DWORD()
    thread = k32.CreateRemoteThread(h, None, 0, C.c_void_p(addr), None, 0, C.byref(tid))
    k32.WaitForSingleObject(thread, 3000)
    time.sleep(0.5)
    return addr


def main() -> int:
    pid = find_pid()
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    result = {"pid": pid}
    netobj = u32(h, 0x8269774)
    if not netobj:
        cave(h, b"\xe8" + struct.pack("<i", 0x803830 - 5) + b"\xc3")
        netobj = u32(h, 0x8269774)
    result["netobj"] = hex(netobj)
    if not netobj:
        return 1

    conn_box = None
    cave_addr = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = bytearray()
    code += b"\x68\xe8\x0a\x00\x00"                 # push 0xAE8
    new_call = len(code)
    code += b"\xe8\x00\x00\x00\x00"                 # call new
    code += b"\x83\xc4\x04"                         # add esp,4
    code += b"\xa3" + struct.pack("<I", cave_addr + 0x800)  # mov [box],eax
    code += b"\x68" + struct.pack("<I", 0)          # arg4
    code += b"\x68" + struct.pack("<I", 0)          # arg3
    code += b"\x68" + struct.pack("<I", 0)          # arg2 bool
    code += b"\x68" + struct.pack("<I", 1)          # arg1
    code += b"\x68" + struct.pack("<I", netobj)     # arg0 netobj
    code += b"\x81\xec\x88\x00\x00\x00"             # sub esp,0x88
    code += b"\xb9\x22\x00\x00\x00"                 # mov ecx,0x22
    code += b"\x31\xc0"                             # xor eax,eax
    code += b"\x89\xe7"                             # mov edi,esp
    code += b"\xf3\xab"                             # rep stosd
    code += b"\x8b\x0d" + struct.pack("<I", cave_addr + 0x800)  # mov ecx,[box]
    ctor_call = len(code)
    code += b"\xe8\x00\x00\x00\x00"                 # call constructor
    code += b"\xa1" + struct.pack("<I", cave_addr + 0x800)      # mov eax,[box]
    code += b"\xc3"
    struct.pack_into("<i", code, new_call + 1, 0xB74220 - (cave_addr + new_call + 5))
    struct.pack_into("<i", code, ctor_call + 1, 0xBA2800 - (cave_addr + ctor_call + 5))
    w(h, cave_addr, bytes(code))
    tid = W.DWORD()
    thread = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave_addr), None, 0, C.byref(tid))
    k32.WaitForSingleObject(thread, 3000)
    exit_code = W.DWORD()
    k32.GetExitCodeThread(thread, C.byref(exit_code))
    conn = u32(h, cave_addr + 0x800) or exit_code.value
    result["conn"] = hex(conn)
    result["vtable"] = hex(u32(h, conn))
    w(h, netobj + 0x4F4, struct.pack("<I", conn))
    w(h, netobj + 0x4F8, struct.pack("<I", 0))
    # netadr at netobj+0x500: type, ip, port
    w(h, netobj + 0x500, struct.pack("<III", 4, 0x0100007F, socket.htons(28969)))
    # call 0xBA4080(conn, netobj+0x500): push arg; mov ecx,conn; call; ret
    addr2 = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code2 = (b"\x68" + struct.pack("<I", netobj + 0x500) +
             b"\xb9" + struct.pack("<I", conn) +
             b"\xe8" + struct.pack("<i", 0xBA4080 - (addr2 + 15)) + b"\xc3")
    w(h, addr2, code2)
    tid2 = W.DWORD()
    thread2 = k32.CreateRemoteThread(h, None, 0, C.c_void_p(addr2), None, 0, C.byref(tid2))
    k32.WaitForSingleObject(thread2, 3000)
    time.sleep(1.0)
    result["after_start"] = {
        "conn_state_0xC8": hex(u32(h, conn + 0xC8)),
        "netobj_4F4": hex(u32(h, netobj + 0x4F4)),
        "netobj_4F8": hex(u32(h, netobj + 0x4F8)),
    }
    out = Path("evidence/experiments/conn-object.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
