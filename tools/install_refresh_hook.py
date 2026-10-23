"""Install the per-call refresh hook that gives 0x66F170 a valid callback.

The 1649370 client never initialises the encoded callback at `cl2+0x30`, so the
decoded `call edx` in 0x66F170 jumps to garbage.  A one-shot write at CL_Init's
return is overwritten by later rebuilds, so this hook patches the heartbeat's
`call 0x5B2C10` site (0x5B31B4) to jump into a cave that:

    cl2 = [0x76638F4] ^ 0x6891D1C7
    [cl2+0x30] = stub ^ (cl2+0x2C) ^ [0xE60B78]
    inc [counter]
    call 0x5B2C10
    jmp 0x5B31B9

and therefore refreshes the callback immediately before every initialiser run.

    python tools/install_refresh_hook.py --install
    python tools/install_refresh_hook.py --read
    python tools/install_refresh_hook.py --revert
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "runs" / "refresh_hook_state.json"

SITE = 0x5B31B4
ORIGINAL = bytes.fromhex("e857faffff")
RESUME = 0x5B31B9
TARGET = 0x5B2C10

CL2_ENCODED = 0x76638F4
CL2_XOR = 0x6891D1C7
KEY = 0xE60B78
CAVE_SIZE = 0x1000
COUNTER_OFFSET = 0x200

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = C.c_void_p
k32.OpenProcess.argtypes = [C.c_uint32, C.c_int, C.c_uint32]
k32.ReadProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualAllocEx.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
k32.VirtualFreeEx.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint32]
k32.FlushInstructionCache.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_client() -> tuple[int, int]:
    pid = sc.find_pid()
    handle = int(k32.OpenProcess(0x1F0FFF, False, pid) or 0)
    if not handle:
        raise SystemExit("OpenProcess failed")
    return pid, handle


def read(handle: int, address: int, size: int) -> bytes | None:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    ok = k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value] if ok and got.value == size else None


def write(handle: int, address: int, data: bytes) -> bool:
    wrote = C.c_size_t()
    ok = k32.WriteProcessMemory(handle, C.c_void_p(address),
                                C.create_string_buffer(data, len(data)), len(data),
                                C.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def build_cave(cave: int, stub: int, counter: int) -> bytes:
    code = bytearray()
    code += b"\x60"                                        # pushad
    code += b"\xa1" + struct.pack("<I", CL2_ENCODED)       # mov eax,[cl2 global]
    code += b"\x35" + struct.pack("<I", CL2_XOR)           # xor eax, key
    code += b"\x89\xc2"                                    # mov edx,eax
    code += b"\x8d\x40\x2c"                                # lea eax,[eax+0x2C]
    code += b"\x8b\x0d" + struct.pack("<I", KEY)           # mov ecx,[0xE60B78]
    code += b"\x33\xc1"                                    # xor eax,ecx
    code += b"\xb9" + struct.pack("<I", stub)              # mov ecx,stub
    code += b"\x33\xc1"                                    # xor eax,ecx
    code += b"\x89\x42\x30"                                # mov [edx+0x30],eax
    code += b"\xff\x05" + struct.pack("<I", counter)       # inc dword [counter]
    code += b"\x61"                                        # popad
    call_at = len(code)
    code += b"\xe8\x00\x00\x00\x00"
    struct.pack_into("<i", code, call_at + 1, TARGET - (cave + call_at + 5))
    jmp_at = len(code)
    code += b"\xe9\x00\x00\x00\x00"
    struct.pack_into("<i", code, jmp_at + 1, RESUME - (cave + jmp_at + 5))
    return bytes(code)


def install() -> int:
    pid, handle = open_client()
    try:
        live = read(handle, SITE, len(ORIGINAL))
        if live != ORIGINAL:
            print(json.dumps({"status": "byte_mismatch", "site": hex(SITE),
                              "expected": ORIGINAL.hex(),
                              "found": live.hex() if live else None}, indent=2))
            return 4
        cave = int(k32.VirtualAllocEx(handle, None, CAVE_SIZE, 0x3000, 0x40) or 0)
        stub = int(k32.VirtualAllocEx(handle, None, 0x100, 0x3000, 0x40) or 0)
        counter = cave + COUNTER_OFFSET
        if not cave or not stub:
            print(json.dumps({"status": "alloc_failed"}, indent=2))
            return 5
        write(handle, stub, b"\x31\xc0\xc3")
        write(handle, counter, bytes(4))
        code = build_cave(cave, stub, counter)
        write(handle, cave, code)
        patch = b"\xe9" + struct.pack("<i", cave - (SITE + 5))
        write(handle, SITE, patch)
        k32.FlushInstructionCache(handle, C.c_void_p(SITE), 5)
        readback = read(handle, SITE, 5)
        row = {"schema": 1, "build": 1649370, "utc": utc(), "pid": pid,
               "site": hex(SITE), "cave": hex(cave), "stub": hex(stub),
               "counter": hex(counter), "patch": patch.hex(),
               "readback": readback.hex() if readback else None,
               "verified": readback == patch}
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(row, indent=2))
        return 0 if row["verified"] else 6
    finally:
        k32.CloseHandle(handle)


def read_state() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    pid, handle = open_client()
    try:
        counter = int(state["counter"], 16)
        hits = read(handle, counter, 4)
        print(json.dumps({"pid": pid, "hits": struct.unpack("<I", hits)[0] if hits else None,
                          "site": state["site"], "cave": state["cave"]}, indent=2))
        return 0
    finally:
        k32.CloseHandle(handle)


def revert() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    pid, handle = open_client()
    try:
        write(handle, int(state["site"], 16), ORIGINAL)
        k32.FlushInstructionCache(handle, C.c_void_p(int(state["site"], 16)), 5)
        print(json.dumps({"status": "reverted", "pid": pid,
                          "readback": (read(handle, int(state["site"], 16), 5) or b"").hex()},
                         indent=2))
        return 0
    finally:
        k32.CloseHandle(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true")
    group.add_argument("--read", action="store_true")
    group.add_argument("--revert", action="store_true")
    args = parser.parse_args()
    if args.install:
        return install()
    if args.read:
        return read_state()
    return revert()


if __name__ == "__main__":
    raise SystemExit(main())
