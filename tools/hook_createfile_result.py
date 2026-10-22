"""Record CreateFileA paths, returned handles, and Win32 errors in Build 1649370.

The existing hook_createfile.py records only input pointers. This hook also
reads the result plus TEB.LastErrorValue immediately after the original call.
Name pointers are read from the target during polling and may become stale;
poll quickly. Install only in a disposable, guarded private client session.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import hook_createfile as base
import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "runs/createfile_result_state.json"
IAT = 0xCA8208
COUNT = 32
STRIDE = 0x10


def u32(number: int) -> bytes:
    return struct.pack("<I", number)


def build_cave(record: int, slot: int) -> bytes:
    code = bytearray()

    def emit(data: bytes) -> None:
        code.extend(data)

    emit(b"\x55\x8b\xec\x83\xec\x04\x60")  # frame, local ring pointer, pushad
    emit(b"\xa1" + u32(record))               # eax = count
    emit(b"\x8d\x50\x01\x89\x15" + u32(record))  # count = eax + 1
    emit(b"\x83\xe0\x1f\xc1\xe0\x04")     # eax = (old count & 31) * 16
    emit(b"\x05" + u32(record + 0x10))
    emit(b"\x89\x45\xfc")                  # [ebp-4] = record entry
    emit(b"\x8b\x55\x04\x89\x10")       # return address
    emit(b"\x8b\x55\x08\x89\x50\x04")  # lpFileName pointer
    emit(b"\x61")                         # popad
    # CreateFileA is stdcall with seven 4-byte arguments. Push the original
    # arguments in reverse order; the callee removes them.
    for displacement in (0x20, 0x1C, 0x18, 0x14, 0x10, 0x0C, 0x08):
        emit(b"\xff\x75" + bytes([displacement]))
    emit(b"\xff\x15" + u32(slot))          # call original CreateFileA
    emit(b"\x8b\x4d\xfc\x89\x41\x08")  # result handle, keep eax
    emit(b"\x64\x8b\x15\x34\x00\x00\x00")  # fs:[0x34] LastErrorValue
    emit(b"\x89\x51\x0c\x8b\xe5\x5d\xc2\x1c\x00")
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.install == args.read:
        parser.error("select exactly one of --install or --read")

    pid, handle = base.open_client()
    row = {"schema": 1, "build": 1649370, "pid": pid,
           "utc": datetime.now(timezone.utc).isoformat()}
    try:
        if args.install:
            cave = base.alloc(handle, 0x1000, 0x40)
            record = base.alloc(handle, 0x1000, 0x04)
            slot = base.alloc(handle, 0x1000, 0x04)
            if not all((cave, record, slot)):
                raise OSError("VirtualAllocEx failed")
            sc.w(handle, record, bytes(0x10 + COUNT * STRIDE))
            original_data = base.read(handle, IAT, 4)
            if len(original_data) != 4:
                raise OSError("could not read CreateFileA IAT")
            original = struct.unpack("<I", original_data)[0]
            sc.w(handle, slot, u32(original))
            code = build_cave(record, slot)
            sc.w(handle, cave, code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if not base.patch_iat(handle, IAT, cave):
                raise OSError("could not patch CreateFileA IAT")
            readback = struct.unpack("<I", base.read(handle, IAT, 4))[0]
            row.update(status="installed" if readback == cave else "readback_mismatch",
                       iat=hex(IAT), original=hex(original), cave=hex(cave),
                       record=hex(record), slot=hex(slot), readback=hex(readback),
                       cave_hex=code.hex())
            STATE.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        else:
            state = json.loads(STATE.read_text(encoding="utf-8"))
            if state["pid"] != pid:
                raise ValueError("saved hook belongs to a different process")
            raw = base.read(handle, int(state["record"], 0), 0x10 + COUNT * STRIDE)
            if len(raw) != 0x10 + COUNT * STRIDE:
                raise OSError("could not read result ring")
            count = struct.unpack_from("<I", raw, 0)[0]
            entries = []
            for sequence in range(max(0, count - COUNT), count):
                offset = 0x10 + (sequence & (COUNT - 1)) * STRIDE
                ret, pointer, result, error = struct.unpack_from("<IIII", raw, offset)
                name = (base.read(handle, pointer, 260) if pointer else b"").split(b"\0", 1)[0]
                entries.append({"sequence": sequence, "caller": hex(ret),
                                "name_ptr": hex(pointer),
                                "name": name.decode("latin-1", "replace"),
                                "handle": hex(result), "last_error": error,
                                "failed": result == 0xFFFFFFFF})
            row.update(status="read", count=count, entries=entries)
    finally:
        sc.k32.CloseHandle(handle)
    encoded = json.dumps(row, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    try:
        print(encoded)
    except UnicodeEncodeError:
        print(encoded.encode("ascii", "backslashreplace").decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
