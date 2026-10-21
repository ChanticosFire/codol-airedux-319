"""Call the whole 0xB81EF0 connect function with a zero 0x88 config block."""
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


def call(h, cave: int):
    tid = W.DWORD()
    thread = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    k32.WaitForSingleObject(thread, 3000)
    time.sleep(0.6)


def main() -> int:
    pid = find_pid()
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    result = {"pid": pid}
    netobj = u32(h, 0x8269774)
    if not netobj:
        c = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
        code = b"\xe8" + struct.pack("<i", 0x803830 - (c + 5)) + b"\xc3"
        w(h, c, code)
        call(h, c)
        netobj = u32(h, 0x8269774)
    result["netobj"] = hex(netobj)
    if not netobj:
        return 1
    cfg = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04))
    # The function copies this 0x88 block to netobj+0x500; put a valid netadr first.
    w(h, cfg, struct.pack("<III", 4, 0x0100007F, socket.htons(28969)))
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    code = bytearray()
    code += b"\x68" + struct.pack("<I", 0)          # arg1 ([ebp+0x94])
    code += b"\x68" + struct.pack("<I", cfg)        # arg0 ([ebp+0x90] config pointer)
    code += b"\x81\xec\x88\x00\x00\x00"             # sub esp,0x88
    code += b"\xb9\x22\x00\x00\x00"                 # mov ecx,0x22
    code += b"\x31\xc0"                             # xor eax,eax
    code += b"\x89\xe7"                             # mov edi,esp
    code += b"\xf3\xab"                             # rep stosd
    code += b"\xb9" + struct.pack("<I", netobj)     # mov ecx,netobj
    call_pos = len(code)
    code += b"\xe8\x00\x00\x00\x00"                 # call 0xB82070 (wrapper)
    code += b"\xc3"
    struct.pack_into("<i", code, call_pos + 1, 0xB82070 - (cave + call_pos + 5))
    w(h, cave, bytes(code))
    call(h, cave)
    result["conn"] = hex(u32(h, netobj + 0x4F4))
    result["state"] = hex(u32(h, netobj + 0x4F8))
    conn = u32(h, netobj + 0x4F4)
    if conn:
        result["vtable"] = hex(u32(h, conn))
        result["conn_c8"] = hex(u32(h, conn + 0xC8))
        result["conn_644"] = hex(u32(h, conn + 0x644))
    out = Path("evidence/experiments/start-conn.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
