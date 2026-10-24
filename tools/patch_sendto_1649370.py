"""Patch CODOL's UDP send path so a real datagram actually leaves the process.

`0x622040` is the packet sender.  Its signature (from the prologue) is:

    [ebp+0x08] = length          <- `cmp ebx, 0x4e6`
    [ebp+0x0c] = data pointer    <- saved to [ebp-0x4f4], used as source
    [ebp+0x24] = channel id      <- `cmp esi, 0x9d`

When the channel lookup or the transport object is missing it falls through to
`0x6221d8`, which is literally `mov ebx, 0xfffffff9` (-7) followed by the shared
epilogue at `0x6221dd` (LeaveCriticalSection + return).  That is why every send
silently reports -7 and no datagram is emitted.

The shipped `--raw-udp-branch` cave copies `[ebp+0x28]` as the length, which is
the wrong slot, so even with the patch installed `sendto` never sees a sane
length.  This tool installs a corrected cave that:

    * writes a sentinel (proves the cave ran),
    * reads data/length from the right slots,
    * creates a UDP socket and calls sendto to 127.0.0.1:<port>,
    * stores socket()/sendto() return values for inspection,
    * returns 0 (success) and jumps to the shared epilogue.

    python tools/patch_sendto_1649370.py --probe
    python tools/patch_sendto_1649370.py --port 28969
    python tools/patch_sendto_1649370.py --port 28969 --restore
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
k32.FlushInstructionCache.restype = W.BOOL

PATCH_SITE = 0x6221D8
EPILOGUE = 0x6221DD
SOCKET_THUNK = 0xCA8548
SENDTO_THUNK = 0xCA8518
SENTINEL = 0xE54BC50
SENTINEL_VALUE = 0xCAFEBABE
ORIGINAL = bytes.fromhex("bbf9ffffff")   # mov ebx, 0xfffffff9

PATCH_LEN = 5


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
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--probe", action="store_true")
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

    def unprotect(va: int, n: int) -> tuple[bool, int]:
        old = W.DWORD()
        ok = bool(k32.VirtualProtectEx(handle, C.c_void_p(va), n, 0x40, C.byref(old)))
        return ok, old.value

    report: dict = {"pid": pid, "site": hex(PATCH_SITE), "port": args.port}
    current = read(PATCH_SITE, PATCH_LEN)
    report["bytes_now"] = current.hex() if current else None
    report["is_original"] = (current == ORIGINAL)
    report["is_patched_jmp"] = bool(current and current[0] == 0xE9)

    if args.probe:
        print(json.dumps(report, indent=2))
        return 0

    if args.restore:
        ok, old = unprotect(PATCH_SITE, len(ORIGINAL))
        restored = write(PATCH_SITE, ORIGINAL)
        k32.VirtualProtectEx(handle, C.c_void_p(PATCH_SITE), len(ORIGINAL), old, C.byref(old))
        report.update(restored=restored, bytes=read(PATCH_SITE, len(ORIGINAL)).hex())
        print(json.dumps(report, indent=2))
        return 0 if restored else 1

    cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")
    sockaddr = cave + 0x100
    sock_slot = cave + 0x200
    send_slot = cave + 0x204
    data_slot = cave + 0x208
    len_slot = cave + 0x20C

    sa = struct.pack("<HH4s8x", 2, socket.htons(args.port), b"\x7f\x00\x00\x01")
    if not write(sockaddr, sa):
        raise SystemExit("write sockaddr failed")

    code = bytearray()
    code += b"\x60"                                        # pushad
    code += b"\xC7\x05" + struct.pack("<I", SENTINEL) + struct.pack("<I", SENTINEL_VALUE)  # mov [sent],imm
    code += b"\x8B\x75\x0C"                                # mov esi,[ebp+0xc]   data
    code += b"\x8B\x7D\x08"                                # mov edi,[ebp+8]     length
    code += b"\x89\x35" + struct.pack("<I", data_slot)     # mov [data_slot],esi
    code += b"\x89\x3D" + struct.pack("<I", len_slot)      # mov [len_slot],edi
    code += b"\x6A\x11\x6A\x02\x6A\x02"                    # push 17,2,2
    code += b"\xFF\x15" + struct.pack("<I", SOCKET_THUNK)  # call [socket]
    code += b"\x8B\xD8"                                    # mov ebx,eax
    code += b"\xA3" + struct.pack("<I", sock_slot)         # mov [sock_slot],eax
    code += b"\x6A\x10"                                    # push 16
    code += b"\x68" + struct.pack("<I", sockaddr)          # push sockaddr
    code += b"\x6A\x00"                                    # push 0
    code += b"\x57"                                        # push edi (len)
    code += b"\x56"                                        # push esi (data)
    code += b"\x53"                                        # push ebx (sock)
    code += b"\xFF\x15" + struct.pack("<I", SENDTO_THUNK)  # call [sendto]
    code += b"\xA3" + struct.pack("<I", send_slot)         # mov [send_slot],eax
    code += b"\x61"                                        # popad
    code += b"\x31\xDB"                                    # xor ebx,ebx  (success)
    rel = (EPILOGUE - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)               # jmp epilogue

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))

    ok, old = unprotect(PATCH_SITE, PATCH_LEN)
    if not ok:
        raise SystemExit("VirtualProtectEx failed")
    jump = b"\xE9" + struct.pack("<I", (cave - (PATCH_SITE + 5)) & 0xFFFFFFFF)
    patched = write(PATCH_SITE, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(PATCH_SITE), PATCH_LEN, old, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(PATCH_SITE), PATCH_LEN)

    report.update(
        patched=patched,
        cave=hex(cave),
        sockaddr=hex(sockaddr),
        slots={"socket": hex(sock_slot), "sendto": hex(send_slot),
               "data": hex(data_slot), "len": hex(len_slot)},
        sentinel=hex(SENTINEL),
        bytes_after=read(PATCH_SITE, PATCH_LEN).hex(),
        code=bytes(code).hex(),
    )
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if patched else 1


if __name__ == "__main__":
    raise SystemExit(main())
