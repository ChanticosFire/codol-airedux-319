"""Make the dedrun secure-profile reader return a zero-filled profile.

The enter-world path drops the client when no mpdata_s exists, and the map GSC
then throws getPlayerData.  This patch replaces CODOL_ReadSecureProfile with a
stub that zeroes the caller's buffer and returns 1, so the attach stage sees a
well-formed all-zero profile.  If the schema accepts it, GSC reads defaults
instead of throwing.

    python tools/patch_dedrun_zeroprofile.py --in <enterworld2.exe> --out <enterworld3.exe>
"""
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

import pefile

READ_SECURE_PROFILE = 0x57BE1A
CAVE = 0x47320E


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="source", type=Path,
                        default=Path(r"runs\2697-enterworld-patched\codol_dedrun_enterworld2.exe"))
    parser.add_argument("--out", dest="target", type=Path,
                        default=Path(r"runs\2697-enterworld-patched\codol_dedrun_enterworld3.exe"))
    args = parser.parse_args()
    raw = bytearray(args.source.read_bytes())
    pe = pefile.PE(str(args.source), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase

    def offset(va: int) -> int:
        return pe.get_offset_from_rva(va - base)

    original = bytes(raw[offset(READ_SECURE_PROFILE):offset(READ_SECURE_PROFILE) + 5])
    if original != b"\x55\x89\xe5\x8d\x64":
        raise SystemExit(f"unexpected prologue: {original.hex()}")
    cave = bytes(raw[offset(CAVE):offset(CAVE) + 32])
    if cave != b"\x90" * 32:
        raise SystemExit(f"cave is not NOP padding: {cave.hex()}")
    stub = bytearray()
    stub += b"\x8b\x7c\x24\x1c"          # mov edi,[esp+0x1c]  (out)
    stub += b"\x8b\x4c\x24\x20"          # mov ecx,[esp+0x20]  (capacity)
    stub += b"\x31\xc0"                  # xor eax,eax
    stub += b"\xf3\xaa"                  # rep stosb
    stub += b"\xb8\x01\x00\x00\x00"      # mov eax,1
    stub += b"\xc3"                      # ret
    jump = b"\xe9" + struct.pack("<i", CAVE - (READ_SECURE_PROFILE + 5))
    raw[offset(READ_SECURE_PROFILE):offset(READ_SECURE_PROFILE) + 5] = jump
    raw[offset(CAVE):offset(CAVE) + len(stub)] = stub
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_bytes(bytes(raw))
    print("stub", stub.hex())
    print("out", args.target, "sha256", sha_file(args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
