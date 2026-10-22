"""Capture the message passed to Com_Error (0x4F82E0) during a map preload.

`preloadmap` ends in a fatal dialog whose text screenshots cannot capture, so
this tool patches the Com_Error prologue with a cave that copies the error code
and the format-string bytes into a dump area inside the same cave.

    python tools/hook_com_error.py --install
    python tools/hook_com_error.py --read
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
STATE = ROOT / "runs" / "com_error_state.json"
COM_ERROR = 0x77C930  # Fatal error (was Com_Error 0x4F82E0)
PROLOGUE = bytes.fromhex("558bec83e4f8")

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
            code += b"\x8b\x44\x24\x20"                                # mov eax,[esp+0x20] (return address)
            code += b"\xa3" + struct.pack("<I", dump + 0x88)
            code += b"\x8b\x44\x24\x24"                                # mov eax,[esp+0x24]
            code += b"\xa3" + struct.pack("<I", dump + 0x80)
            code += b"\x8b\x4c\x24\x28"                                # mov ecx,[esp+0x28]
            code += b"\x85\xc9"                                        # test ecx,ecx
            code += b"\x74\x19"                                        # jz skip
            code += b"\x89\x0d" + struct.pack("<I", dump + 0x84)       # mov [dump+0x84],ecx
            code += b"\xbe" + struct.pack("<I", dump + 0x84)           # mov esi,dump+0x84
            code += b"\x8b\x30"                                        # mov esi,[eax]
            code += b"\xbe" + struct.pack("<I", 0)                     # placeholder
            code += b"\xbf" + struct.pack("<I", dump)                  # mov edi,dump
            code += b"\xb9\x50\x00\x00\x00"                            # mov ecx,0x50
            code += b"\xa1" + struct.pack("<I", dump + 0x84)           # mov eax,[dump+0x84]
            code += b"\x89\xc6"                                        # mov esi,eax
            code += b"\xf3\xa4"                                        # rep movsb
            code += b"\x61"                                            # popad
            code += PROLOGUE
            target = COM_ERROR + len(PROLOGUE)
            code += b"\xe9" + struct.pack("<I", (target - (cave + len(code) + 5)) & 0xFFFFFFFF)
            if not write(handle, cave, bytes(code)):
                row["status"] = "cave_write_failed"
            else:
                K32.FlushInstructionCache = getattr(K32, "FlushInstructionCache")
                old = C.c_uint32(0)
                K32.VirtualProtectEx(handle, C.c_void_p(COM_ERROR), len(PROLOGUE), 0x40,
                                     C.byref(old))
                patch = b"\xe9" + struct.pack("<I", (cave - (COM_ERROR + 5)) & 0xFFFFFFFF) + b"\x90"
                ok = write(handle, COM_ERROR, patch)
                row.update(status="installed" if ok else "patch_failed",
                           cave=hex(cave), dump=hex(dump))
                STATE.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        elif args.read:
            saved = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
            dump = int(saved.get("dump", "0x0"), 16)
            data = read(handle, dump, 0x90) if dump else None
            code = read(handle, dump + 0x80, 4) if dump else None
            ret = read(handle, dump + 0x88, 4) if dump else None
            row.update(dump=saved.get("dump"),
                       return_address=hex(struct.unpack("<I", ret)[0]) if ret else None,
                       error_code=hex(struct.unpack("<I", code)[0]) if code else None,
                       text=(data.split(b"\x00")[0].decode("latin-1") if data else None),
                       status="read" if data else "read_failed")
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
