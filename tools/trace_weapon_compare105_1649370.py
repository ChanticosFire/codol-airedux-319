"""Trace string comparisons while the 1649370 weapon table count is 105.

At 0x42F3B3 the lookup function has just compared one registered weapon name
to the requested name. EBX is the candidate index. Only comparisons while the
global weapon table count is 105 are captured, isolating the first known ID
divergence without assuming a register survives the string comparison call.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from pathlib import Path

from trace_weapon_registration_1649370 import k32, patch, read, rel32, write

TARGET = 0x42F3B3
ORIGINAL = bytes.fromhex("83c40485c0")  # add esp,4; test eax,eax
CAPACITY = 512
COUNT_OFFSET = 0x200
RECORD_OFFSET = 0x1000
RECORD_SIZE = 16


def build_code(cave: int) -> bytes:
    count_addr = cave + COUNT_OFFSET
    records_addr = cave + RECORD_OFFSET
    code = bytearray(b"\x60")
    code += b"\x81\x3d" + struct.pack("<I", 0x827F738) + struct.pack("<I", 105)
                                                       # cmp dword [table_count],105
    skip_first = len(code)
    code += b"\x0f\x85\x00\x00\x00\x00"        # jne done
    code += b"\x8b\x0d" + struct.pack("<I", count_addr)
    code += b"\x81\xf9" + struct.pack("<I", CAPACITY)
    skip_second = len(code)
    code += b"\x0f\x83\x00\x00\x00\x00"        # jae done
    code += b"\x8b\xd1"                          # mov edx,ecx
    code += b"\x6b\xd2\x10"                      # imul edx,edx,16
    code += b"\x81\xc2" + struct.pack("<I", records_addr)
    code += b"\x89\x1a"                          # [edx]=ebx candidate index
    code += b"\x89\x42\x04"                      # [edx+4]=eax compare result
    code += b"\x89\x72\x08"                      # [edx+8]=esi candidate name
    code += b"\x89\x7a\x0c"                      # [edx+12]=edi bound
    code += b"\xff\x05" + struct.pack("<I", count_addr)
    done = len(code)
    code[skip_first + 2:skip_first + 6] = rel32(cave + skip_first + 6, cave + done)
    code[skip_second + 2:skip_second + 6] = rel32(cave + skip_second + 6, cave + done)
    code += b"\x61" + ORIGINAL
    code += b"\xe9" + rel32(cave + len(code) + 5, TARGET + len(ORIGINAL))
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--meta", type=Path, required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--read", action="store_true")
    mode.add_argument("--restore", action="store_true")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    try:
        if args.install:
            before = read(handle, TARGET, len(ORIGINAL))
            if before != ORIGINAL:
                raise SystemExit(f"compare site mismatch: {before.hex() if before else None}")
            cave = int(k32.VirtualAllocEx(handle, None, 0x10000, 0x3000, 0x40) or 0)
            if not cave or not write(handle, cave, build_code(cave)):
                raise SystemExit("trace cave setup failed")
            if not patch(handle, TARGET, b"\xe9" + rel32(TARGET + 5, cave)):
                raise SystemExit("compare site hook failed")
            report = {"pid": args.pid, "target": hex(TARGET), "cave": hex(cave),
                      "original": ORIGINAL.hex()}
            args.meta.parent.mkdir(parents=True, exist_ok=True)
            args.meta.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
            return 0
        meta = json.loads(args.meta.read_text(encoding="utf-8"))
        if meta["pid"] != args.pid or meta["target"] != hex(TARGET):
            raise SystemExit("metadata does not match client")
        cave = int(meta["cave"], 16)
        if args.restore:
            if not patch(handle, TARGET, ORIGINAL):
                raise SystemExit("compare site restore failed")
            print(json.dumps({"pid": args.pid, "restored": read(handle, TARGET, 5) == ORIGINAL}))
            return 0
        raw_count = read(handle, cave + COUNT_OFFSET, 4)
        if not raw_count:
            raise SystemExit("trace count unreadable")
        count = min(struct.unpack("<I", raw_count)[0], CAPACITY)
        blob = read(handle, cave + RECORD_OFFSET, count * RECORD_SIZE) if count else b""
        if blob is None:
            raise SystemExit("trace buffer unreadable")
        rows = []
        for pos in range(0, len(blob), RECORD_SIZE):
            index, compared, pointer, bound = struct.unpack_from("<IIII", blob, pos)
            name_bytes = read(handle, pointer, 96) if pointer else None
            name = name_bytes.split(b"\0", 1)[0].decode("latin-1", "replace") if name_bytes else None
            rows.append({"index": index, "compared": compared, "candidate": name, "bound": bound})
        report = {"pid": args.pid, "count": count, "last": rows[-8:], "rows": rows}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}))
        return 0
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
