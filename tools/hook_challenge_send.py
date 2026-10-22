"""Probe the argument passed to the 1649370 challenge send helper 0x6751F0.

`0x6751F0` only forwards the packet when its type argument equals 2; any other
value makes the send silently fail and the caller reports
EXE_CLIENTFAILEDTOCHALLENGE.  This hook records the type argument plus the two
other incoming arguments so we can see what the caller actually passes.

    python tools/hook_challenge_send.py --install
    python tools/hook_challenge_send.py --read
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
STATE = ROOT / "runs" / "challenge_send_state.json"
TARGET = 0x6751F0
PROLOGUE = bytes.fromhex("558bec8b4d0c")  # push ebp; mov ebp,esp; mov ecx,[ebp+0xc] (6 bytes: jmp needs 5)

K32 = sc.k32
K32.VirtualAllocEx.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
K32.VirtualAllocEx.restype = C.c_void_p
K32.VirtualProtectEx.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint32,
                                 C.POINTER(C.c_uint32)]


def read(handle, address: int, size: int):
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    ok = K32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw if ok and got.value == size else None


def write(handle, address: int, data: bytes) -> bool:
    wrote = C.c_size_t()
    ok = K32.WriteProcessMemory(handle, C.c_void_p(address),
                                C.create_string_buffer(data, len(data)),
                                len(data), C.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = K32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    row = {"schema": 1, "build": 1649370, "pid": pid,
           "utc": datetime.now(timezone.utc).isoformat()}
    try:
        if args.install:
            cave = int(K32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40))
            dump = cave + 0x1000
            code = bytearray(b"\x60")                                  # pushad
            code += b"\x8b\x44\x24\x2c"                                # mov eax,[esp+0x2c] (arg2=type)
            code += b"\xa3" + struct.pack("<I", dump + 0x00)
            code += b"\x8b\x44\x24\x28"                                # mov eax,[esp+0x28] (arg1)
            code += b"\xa3" + struct.pack("<I", dump + 0x04)
            code += b"\x8b\x44\x24\x20"                                # mov eax,[esp+0x20] (return addr)
            code += b"\xa3" + struct.pack("<I", dump + 0x08)
            code += b"\x61"                                            # popad
            code += PROLOGUE
            target = TARGET + len(PROLOGUE)
            code += b"\xe9" + struct.pack("<I", (target - (cave + len(code) + 5)) & 0xFFFFFFFF)
            if not write(handle, cave, bytes(code)):
                row["status"] = "cave_write_failed"
            else:
                getattr(K32, "FlushInstructionCache")(handle, C.c_void_p(cave), len(code))
                old = C.c_uint32(0)
                K32.VirtualProtectEx(handle, C.c_void_p(TARGET), len(PROLOGUE), 0x40, C.byref(old))
                if not write(handle, TARGET, b"\xe9" + struct.pack("<I", (cave - (TARGET + 5)) & 0xFFFFFFFF)):
                    row["status"] = "patch_failed"
                else:
                    row.update(status="installed", cave=hex(cave), dump=hex(dump))
                    STATE.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
        elif args.read:
            saved = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
            dump = int(saved.get("dump", "0x0"), 16)
            data = read(handle, dump, 0x10) if dump else None
            if data:
                row.update(dump=saved.get("dump"),
                           type_arg=struct.unpack("<I", data[0:4])[0],
                           arg1=hex(struct.unpack("<I", data[4:8])[0]),
                           return_address=hex(struct.unpack("<I", data[8:12])[0]),
                           status="read")
            else:
                row["status"] = "read_failed"
        else:
            row["status"] = "no_action"
    finally:
        K32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
