"""Experimental process-local exact-name fallback for weapon table lookups.

The original 0x42F2F0 returns 0 for an already registered alt-fire name in
the current offline client. Before entering that function, scan only the
registered weapon table for an exact existing name. Return its existing ID on
a match; otherwise execute the original function unchanged. This is a probe,
not a service protocol fix or a default client patch.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from pathlib import Path

from trace_weapon_registration_1649370 import k32, patch, read, rel32, write

TARGET = 0x42F2F0
ORIGINAL = bytes.fromhex("558bec518b4d08")
COUNT = 0x827F738
TABLE = 0x1988B50
HITS_OFF = 0x200
LAST_ID_OFF = 0x204
LAST_NAME_OFF = 0x208


def build_code(cave: int) -> bytes:
    code = bytearray()
    labels: dict[str, int] = {}
    jumps: list[tuple[int, str]] = []

    def emit(data: bytes) -> None:
        code.extend(data)

    def mark(name: str) -> None:
        labels[name] = len(code)

    def branch(opcode: bytes, label: str) -> None:
        at = len(code)
        emit(opcode + b"\0\0\0\0")
        jumps.append((at + len(opcode), label))

    emit(b"\x53\x56\x57")                          # push ebx,esi,edi
    emit(b"\x8b\x74\x24\x10")                      # mov esi,[esp+16] input name
    emit(b"\x8b\x0d" + struct.pack("<I", COUNT))    # mov ecx,[count]
    emit(b"\xbb\x01\x00\x00\x00")                 # mov ebx,1
    emit(b"\x3b\xd9")                              # cmp ebx,ecx
    branch(b"\x0f\x87", "notfound")                 # ja notfound
    mark("scan")
    emit(b"\x8b\x3c\x9d" + struct.pack("<I", TABLE)) # mov edi,[ebx*4+table]
    emit(b"\x85\xff")                              # test edi,edi
    branch(b"\x0f\x84", "next")
    emit(b"\x8b\x3f\x85\xff")                    # mov edi,[edi]; test edi,edi
    branch(b"\x0f\x84", "next")
    emit(b"\x8b\xd6")                              # mov edx,esi
    mark("compare")
    emit(b"\x8a\x07\x3a\x02")                    # mov al,[edi]; cmp al,[edx]
    branch(b"\x0f\x85", "next")
    emit(b"\x84\xc0")                              # test al,al
    branch(b"\x0f\x84", "found")
    emit(b"\x47\x42")                              # inc edi; inc edx
    branch(b"\xe9", "compare")
    mark("next")
    emit(b"\x43\x3b\xd9")                         # inc ebx; cmp ebx,ecx
    branch(b"\x0f\x86", "scan")                     # jbe scan
    mark("notfound")
    emit(b"\x5f\x5e\x5b")                         # pop edi,esi,ebx
    emit(ORIGINAL)                                   # stolen prologue
    branch(b"\xe9", "resume")
    mark("found")
    emit(b"\xff\x05" + struct.pack("<I", cave + HITS_OFF))
    emit(b"\x89\x1d" + struct.pack("<I", cave + LAST_ID_OFF))
    emit(b"\x89\x35" + struct.pack("<I", cave + LAST_NAME_OFF))
    emit(b"\x8b\xc3\x5f\x5e\x5b\xc3")          # eax=ebx; restore; ret

    for displacement_at, label in jumps:
        destination = (TARGET + len(ORIGINAL)) if label == "resume" else cave + labels[label]
        code[displacement_at:displacement_at + 4] = rel32(cave + displacement_at + 4, destination)
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--meta", type=Path, required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--read", action="store_true")
    mode.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    try:
        if args.install:
            before = read(handle, TARGET, len(ORIGINAL))
            if before != ORIGINAL:
                raise SystemExit(f"lookup prologue mismatch: {before.hex() if before else None}")
            cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
            if not cave or not write(handle, cave, build_code(cave)):
                raise SystemExit("lookup cave setup failed")
            if not patch(handle, TARGET, b"\xe9" + rel32(TARGET + 5, cave) + b"\x90\x90"):
                raise SystemExit("lookup entry patch failed")
            report = {"pid": args.pid, "target": hex(TARGET), "cave": hex(cave),
                      "original": ORIGINAL.hex(), "installed": True}
            args.meta.parent.mkdir(parents=True, exist_ok=True)
            args.meta.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
            return 0
        meta = json.loads(args.meta.read_text(encoding="utf-8"))
        if meta["pid"] != args.pid or meta["target"] != hex(TARGET):
            raise SystemExit("metadata does not match client")
        if args.restore:
            if not patch(handle, TARGET, ORIGINAL):
                raise SystemExit("lookup fallback restore failed")
            print(json.dumps({"pid": args.pid, "restored": read(handle, TARGET, len(ORIGINAL)) == ORIGINAL}))
            return 0
        cave = int(meta["cave"], 16)
        values = [read(handle, cave + offset, 4) for offset in (HITS_OFF, LAST_ID_OFF, LAST_NAME_OFF)]
        if any(value is None for value in values):
            raise SystemExit("lookup counters unreadable")
        hits, last_id, pointer = (struct.unpack("<I", value)[0] for value in values)
        name_bytes = read(handle, pointer, 96) if pointer else None
        report = {"pid": args.pid, "hits": hits, "last_id": last_id,
                  "last_name": name_bytes.split(b"\0", 1)[0].decode("latin-1", "replace") if name_bytes else None}
        print(json.dumps(report))
        return 0
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
