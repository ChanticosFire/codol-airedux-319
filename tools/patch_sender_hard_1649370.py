"""Replace CODOL's packet sender with a direct UDP sendto.

`0x622040` is reached for real (traced: `[ebp+8]=0x26` length, `[ebp+0xc]=data`)
but its internal channel lookup rejects the only channel value the state machine
accepts (`0x9d` >= `0x9d`), so it always returns -7 and nothing leaves the
process.

Its calling convention is cdecl (`0x77FB80` does `call 0x622040` then
`add esp,0x20`), and the parameters we need are confirmed:

    [ebp+0x08] = length
    [ebp+0x0c] = data pointer

So the whole function can be replaced by: create a UDP socket, sendto
127.0.0.1:<port>, return 0.

    python tools/patch_sender_hard_1649370.py --probe
    python tools/patch_sender_hard_1649370.py --port 28969
    python tools/patch_sender_hard_1649370.py --restore
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import socket
import struct
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)

k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.VirtualProtectEx.restype = W.BOOL
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]

SENDER = 0x622040
SOCKET_THUNK = 0xCA8548
SENDTO_THUNK = 0xCA8518
STAT_SOCK = 0xE54BC90
STAT_RET = 0xE54BC94
STAT_LEN = 0xE54BC98
STAT_HEAD = 0xE54BC9C

PROLOGUE = bytes.fromhex("558bec81ec0c050000")   # push ebp; mov ebp,esp; sub esp,0x50c


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=28969)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, n: int) -> bytes | None:
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, n, C.byref(got)) or got.value != n:
            return None
        return buf.raw

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    def u32(va: int) -> int | None:
        d = read(va, 4)
        return struct.unpack("<I", d)[0] if d else None

    current = read(SENDER, 9)
    report = {
        "pid": pid, "sender": hex(SENDER), "port": args.port,
        "bytes_now": current.hex() if current else None,
        "is_original": current == PROLOGUE,
        "is_patched": bool(current and current[0] == 0xE9),
        "stats": {"sock": u32(STAT_SOCK), "ret": u32(STAT_RET),
                  "len": u32(STAT_LEN), "head": u32(STAT_HEAD)},
    }
    if args.probe:
        print(json.dumps(report, indent=2))
        return 0

    if args.restore:
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(SENDER), len(PROLOGUE), 0x40, C.byref(old))
        ok = write(SENDER, PROLOGUE)
        k32.VirtualProtectEx(handle, C.c_void_p(SENDER), len(PROLOGUE), old.value, C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(SENDER), len(PROLOGUE))
        report.update(restored=ok, bytes_after=read(SENDER, 9).hex())
        print(json.dumps(report, indent=2))
        return 0 if ok else 1

    cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")
    sockaddr = cave + 0x100
    sa = struct.pack("<HH4s8x", 2, socket.htons(args.port), b"\x7f\x00\x00\x01")
    if not write(sockaddr, sa):
        raise SystemExit("write sockaddr failed")

    code = bytearray()
    code += b"\x55\x8B\xEC"                                # push ebp; mov ebp,esp  (rebuild frame!)
    code += b"\x60"                                        # pushad
    code += b"\x8B\x75\x08"                                # mov esi,[ebp+8]   length
    code += b"\x8B\x7D\x0C"                                # mov edi,[ebp+0xc] data
    code += b"\x6A\x11\x6A\x02\x6A\x02"                    # push 17,2,2
    code += b"\xFF\x15" + struct.pack("<I", SOCKET_THUNK)  # call [socket]
    code += b"\x8B\xD8"                                    # mov ebx,eax
    code += b"\xA3" + struct.pack("<I", STAT_SOCK)         # mov [stat_sock],eax
    code += b"\x89\x35" + struct.pack("<I", STAT_LEN)      # mov [stat_len],esi
    code += b"\x8B\x0F"                                    # mov ecx,[edi]
    code += b"\x89\x0D" + struct.pack("<I", STAT_HEAD)     # mov [stat_head],ecx
    code += b"\x6A\x10"                                    # push 16
    code += b"\x68" + struct.pack("<I", sockaddr)          # push sockaddr
    code += b"\x6A\x00"                                    # push 0
    code += b"\x56"                                        # push esi (len)
    code += b"\x57"                                        # push edi (data)
    code += b"\x53"                                        # push ebx (sock)
    code += b"\xFF\x15" + struct.pack("<I", SENDTO_THUNK)  # call [sendto]
    code += b"\xA3" + struct.pack("<I", STAT_RET)          # mov [stat_ret],eax
    code += b"\x61"                                        # popad
    code += b"\x33\xC0"                                    # xor eax,eax
    code += b"\x5D"                                        # pop ebp
    code += b"\xC3"                                        # ret

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))

    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(SENDER), len(PROLOGUE), 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (SENDER + 5)) & 0xFFFFFFFF)
    jump += b"\x90" * (len(PROLOGUE) - 5)
    patched = write(SENDER, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(SENDER), len(PROLOGUE), old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(SENDER), len(PROLOGUE))

    for slot in (STAT_SOCK, STAT_RET, STAT_LEN, STAT_HEAD):
        write(slot, b"\x00\x00\x00\x00")

    report.update(patched=patched, cave=hex(cave), sockaddr=hex(sockaddr),
                  code=bytes(code).hex(), bytes_after=read(SENDER, 9).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if patched else 1


if __name__ == "__main__":
    raise SystemExit(main())
