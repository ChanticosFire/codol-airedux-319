"""Hook ws2_32!sendto inside CODOL to prove whether any UDP datagram is emitted.

Every in-game send path in this build is reached through an encrypted function
pointer, so call-graph scans and pointer scans both come back empty, and hooking
the game's own sender (`0x622040`) showed it is never invoked.  The one place all
UDP traffic must pass is the imported API itself, whose address sits at
`IAT 0xCA8518`.

The stub is transparent: it records the caller's return address plus the
(socket, buffer, length) arguments, replays the five stolen prologue bytes and
jumps back.  Registers and stack are preserved, so the API behaves normally.

    python tools/hook_sendto_1649370.py --probe
    python tools/hook_sendto_1649370.py                 # install
    python tools/hook_sendto_1649370.py --read
    python tools/hook_sendto_1649370.py --restore
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
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

IAT_SENDTO = 0xCA8518
# pushad(32) then: [esp+0x20]=retaddr [esp+0x24]=s [esp+0x28]=buf [esp+0x2c]=len
SLOT_COUNT = 0xE54BC70
SLOT_RET = 0xE54BC74
SLOT_SOCK = 0xE54BC78
SLOT_BUF = 0xE54BC7C
SLOT_LEN = 0xE54BC80
SLOT_HEAD = 0xE54BC84        # first 4 bytes of the datagram
PROLOGUE = bytes.fromhex("8bff558bec")
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
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--iat", type=lambda v: int(v, 0), default=IAT_SENDTO,
                    help="IAT slot to hook: send=0xCA84E0 sendto=0xCA8518 connect=0xCA84F0")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--read", action="store_true")
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

    def u32(va: int) -> int | None:
        d = read(va, 4)
        return struct.unpack("<I", d)[0] if d else None

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    target = u32(args.iat)
    if not target:
        raise SystemExit("sendto IAT slot is null")
    entry = read(target, PATCH_LEN)
    report: dict = {
        "pid": pid, "sendto": hex(target),
        "entry_bytes": entry.hex() if entry else None,
        "is_original": entry == PROLOGUE,
        "is_hooked": bool(entry and entry[0] == 0xE9),
        "counters": {"count": u32(SLOT_COUNT), "ret": u32(SLOT_RET),
                     "sock": u32(SLOT_SOCK), "buf": u32(SLOT_BUF),
                     "len": u32(SLOT_LEN), "head": u32(SLOT_HEAD)},
    }
    if args.probe or args.read:
        for key in ("ret", "sock", "buf", "head"):
            if isinstance(report["counters"].get(key), int):
                report["counters"][key] = hex(report["counters"][key])
        print(json.dumps(report, indent=2))
        return 0

    if args.restore:
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(target), PATCH_LEN, 0x40, C.byref(old))
        ok = write(target, PROLOGUE)
        k32.VirtualProtectEx(handle, C.c_void_p(target), PATCH_LEN, old.value, C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(target), PATCH_LEN)
        report.update(restored=ok, bytes=read(target, PATCH_LEN).hex())
        print(json.dumps(report, indent=2))
        return 0 if ok else 1

    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                        # pushad
    code += b"\x8B\x44\x24\x20"                            # mov eax,[esp+0x20]  retaddr
    code += b"\xA3" + struct.pack("<I", SLOT_RET)
    code += b"\x8B\x44\x24\x24"                            # mov eax,[esp+0x24]  s
    code += b"\xA3" + struct.pack("<I", SLOT_SOCK)
    code += b"\x8B\x4C\x24\x28"                            # mov ecx,[esp+0x28]  buf
    code += b"\x89\x0D" + struct.pack("<I", SLOT_BUF)
    code += b"\x8B\x54\x24\x2C"                            # mov edx,[esp+0x2c]  len
    code += b"\x89\x15" + struct.pack("<I", SLOT_LEN)
    code += b"\x8B\x31"                                    # mov esi,[ecx]       first 4 bytes
    code += b"\x89\x35" + struct.pack("<I", SLOT_HEAD)
    code += b"\xFF\x05" + struct.pack("<I", SLOT_COUNT)    # inc dword [count]
    code += b"\x61"                                        # popad
    code += PROLOGUE                                       # replay stolen bytes
    rel = (target + PATCH_LEN - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)               # jmp sendto+5

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))

    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(target), PATCH_LEN, 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (target + 5)) & 0xFFFFFFFF)
    hooked = write(target, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(target), PATCH_LEN, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(target), PATCH_LEN)

    # zero the counters so later deltas are meaningful
    for slot in (SLOT_COUNT, SLOT_RET, SLOT_SOCK, SLOT_BUF, SLOT_LEN, SLOT_HEAD):
        write(slot, b"\x00\x00\x00\x00")

    report.update(hooked=hooked, cave=hex(cave), code=bytes(code).hex(),
                  entry_after=read(target, PATCH_LEN).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if hooked else 1


if __name__ == "__main__":
    raise SystemExit(main())
