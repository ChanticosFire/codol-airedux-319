"""Trace who calls CODOL's packet sender, without knowing the caller statically.

All interesting functions in this build are reached through encrypted function
pointers (`0x66F20E call edx`, `edx = [edi+0x20] ^ [edi+0x24] ^ [0xE60B78]`), so
static call-graph and pointer scans both come back empty.  The practical way to
learn whether a function is ever invoked - and from where - is to hook its entry
with a *transparent* stub:

    pushad
    mov  eax, [esp+0x20]        ; original [esp] == caller's return address
    mov  [slot_ret], eax
    inc  dword [slot_count]
    popad
    push ebp                    ; replay original prologue
    mov  ebp, esp
    jmp  0x622043               ; continue at "sub esp,0x50c"

`pushad` shifts esp by 32 bytes, so the caller's return address sits at
`[esp+0x20]` inside the stub.  The stub preserves every register and the stack,
so the hooked function behaves exactly as before.

    python tools/trace_sender_1649370.py --probe
    python tools/trace_sender_1649370.py             # install
    python tools/trace_sender_1649370.py --read      # show counters
    python tools/trace_sender_1649370.py --restore
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

SENDER = 0x622040
CONTINUE_AT = 0x622043          # right after "push ebp; mov ebp, esp"
ORIGINAL = bytes.fromhex("558bec81ec0c050000")   # push ebp; mov ebp,esp; sub esp,0x50c
SLOT_RET = 0xE54BC60            # last caller return address
SLOT_COUNT = 0xE54BC64          # invocation counter
SLOT_LAST_DATA = 0xE54BC68
SLOT_LAST_LEN = 0xE54BC6C
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

    counters = {"count": u32(SLOT_COUNT), "last_ret": u32(SLOT_RET),
                "last_data": u32(SLOT_LAST_DATA), "last_len": u32(SLOT_LAST_LEN)}
    entry = read(SENDER, PATCH_LEN)
    report: dict = {
        "pid": pid,
        "sender": hex(SENDER),
        "entry_bytes": entry.hex() if entry else None,
        "is_original": entry == ORIGINAL[:PATCH_LEN],
        "is_hooked": bool(entry and entry[0] == 0xE9),
        "counters": {k: (hex(v) if isinstance(v, int) and v is not None else v)
                     for k, v in counters.items()},
        "slots": {"ret": hex(SLOT_RET), "count": hex(SLOT_COUNT)},
    }

    if args.probe or args.read:
        print(json.dumps(report, indent=2))
        return 0

    if args.restore:
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(SENDER), len(ORIGINAL), 0x40, C.byref(old))
        ok = write(SENDER, ORIGINAL)
        k32.VirtualProtectEx(handle, C.c_void_p(SENDER), len(ORIGINAL), old.value, C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(SENDER), len(ORIGINAL))
        report.update(restored=ok, bytes=read(SENDER, len(ORIGINAL)).hex())
        print(json.dumps(report, indent=2))
        return 0 if ok else 1

    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                              # pushad
    code += b"\x8B\x44\x24\x20"                                  # mov eax,[esp+0x20]  caller ret
    code += b"\xA3" + struct.pack("<I", SLOT_RET)                # mov [slot_ret],eax
    code += b"\xFF\x05" + struct.pack("<I", SLOT_COUNT)          # inc dword [slot_count]
    # record data/len per the confirmed signature ([ebp+0xc] / [ebp+8])
    code += b"\x8B\x4C\x24\x24"                                  # mov ecx,[esp+0x24]  caller arg0? (unused)
    code += b"\x61"                                              # popad
    code += b"\x55\x8B\xEC"                                      # push ebp; mov ebp,esp
    rel = (CONTINUE_AT - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)                     # jmp 0x622043

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))

    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(SENDER), PATCH_LEN, 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (SENDER + 5)) & 0xFFFFFFFF)
    hooked = write(SENDER, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(SENDER), PATCH_LEN, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(SENDER), PATCH_LEN)

    report.update(hooked=hooked, cave=hex(cave), code=bytes(code).hex(),
                  entry_after=read(SENDER, PATCH_LEN).hex())
    print(json.dumps(report, indent=2))
    k32.CloseHandle(handle)
    return 0 if hooked else 1


if __name__ == "__main__":
    raise SystemExit(main())
