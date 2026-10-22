"""Patch the dedrun copy so CS_PRIMED clients enter the world on the main thread.

SV_SendClientMessages already runs per client in the server loop.  At
0x48AAA9..0x48AAC1 it branches on state and calls SV_BuildClientSnapshot
(regparm eax=client).  This patch:

  * 0x48AAB5: cmp eax,1 -> cmp eax,3   (accept CS_PRIMED as well)
  * 0x48AABA: replace "mov eax,ebx; call 0x489081" with "jmp 0x48B80C"
  * 0x48B80C (52-byte NOP cave): stub that calls SV_ClientEnterWorld(client,
    NULL) for state 3 and otherwise keeps calling SV_BuildClientSnapshot

    python tools/patch_dedrun_enterworld.py
"""
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

import pefile

DEFAULT_EXE = Path(r"runs\2697-defer-patched\codol_dedrun_deferpatch.exe")
DEFAULT_OUT = Path(r"runs\2697-enterworld-patched\codol_dedrun_enterworld.exe")
CAVE = 0x48B80C
SITE_CMP = 0x48AAB5
SITE_JMP = 0x48AABA
SITE_DROP = 0x4707C5
AFTER_DROP = 0x470728
RESUME = 0x48AAC1
ENTER_WORLD = 0x4705F4
BUILD_SNAPSHOT = 0x489081


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_stub() -> bytes:
    # push ebx
    # mov eax,[ebx]
    # cmp eax,3
    # jne build_cold
    # push 0
    # push ebx
    # call SV_ClientEnterWorld
    # add esp,8
    # jmp resume
    # build_cold:
    # mov eax,ebx
    # call SV_BuildClientSnapshot
    # jmp resume
    stub = bytearray()
    stub += b"\x53"                      # push ebx
    stub += b"\x8b\x03"                  # mov eax,[ebx]
    stub += b"\x83\xf8\x03"              # cmp eax,3
    stub += b"\x75\x10"                  # jne +0x10 -> build_cold
    stub += b"\x6a\x00"                  # push 0
    stub += b"\x53"                      # push ebx
    call1 = CAVE + len(stub)
    stub += b"\xe8" + struct.pack("<i", ENTER_WORLD - (call1 + 5))
    stub += b"\x83\xc4\x08"              # add esp,8
    jmp1 = CAVE + len(stub)
    stub += b"\xe9" + struct.pack("<i", RESUME - (jmp1 + 5))
    assert CAVE + len(stub) == CAVE + 0x18, hex(CAVE + len(stub))
    stub += b"\x8b\xc3"                  # mov eax,ebx  (build_cold)
    call2 = CAVE + len(stub)
    stub += b"\xe8" + struct.pack("<i", BUILD_SNAPSHOT - (call2 + 5))
    jmp2 = CAVE + len(stub)
    stub += b"\xe9" + struct.pack("<i", RESUME - (jmp2 + 5))
    return bytes(stub)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    raw = bytearray(args.exe.read_bytes())
    pe = pefile.PE(str(args.exe), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase

    def offset(va: int) -> int:
        return pe.get_offset_from_rva(va - base)

    checks = {
        SITE_CMP: bytes.fromhex("83f801"),
        SITE_JMP: bytes.fromhex("89d8e8c0e5ffff"),
        SITE_DROP: bytes.fromhex("e881e6ffff"),
        CAVE: b"\x90" * len(build_stub()),
    }
    for va, expected in checks.items():
        actual = bytes(raw[offset(va):offset(va) + len(expected)])
        if actual != expected:
            raise SystemExit(f"unexpected bytes at {hex(va)}: {actual.hex()}")
    stub = build_stub()
    raw[offset(SITE_CMP):offset(SITE_CMP) + 3] = b"\x83\xf8\x03"
    jump_back = b"\xe9" + struct.pack("<i", CAVE - (SITE_JMP + 5)) + b"\x90\x90"
    raw[offset(SITE_JMP):offset(SITE_JMP) + len(jump_back)] = jump_back
    raw[offset(CAVE):offset(CAVE) + len(stub)] = stub
    # A missing secure profile must not drop the client before ClientBegin; the
    # 1649370 offline profile has no mpdata_s.  Jump straight into the normal
    # enter-world continuation instead of calling SV_DropClient.
    skip_drop = b"\xe9" + struct.pack("<i", AFTER_DROP - (SITE_DROP + 5))
    raw[offset(SITE_DROP):offset(SITE_DROP) + len(skip_drop)] = skip_drop
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bytes(raw))
    print("stub", stub.hex())
    print("out", args.out, "sha256", sha_file(args.out))
    print("original sha256", sha_file(args.exe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
