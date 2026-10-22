"""Locate and patch CODOL_DeferConfigstringCommand in the 2697 dedrun binary.

The 2697 source defers every configstring update while a client is CS_PRIMED
and only pumps the backlog once the client is CS_ACTIVE; the 1649370 client
waits for those configstrings before sending its first usercmd, so both sides
stall.  Patching the defer entry to `xor eax,eax; ret` makes configstring
commands queue normally while the client is still priming.

    python tools/patch_dedrun_defer.py --analyze
    python tools/patch_dedrun_defer.py --apply --out runs/dedrun-defer-patched.exe
"""
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

import pefile

DEFAULT_EXE = Path(r"runs\2697-server-test\codol_dedrun.exe")
STRING = b"CoDOL configstring %lu deferred for client %u (%d pending)"
PROLOGUES = (bytes.fromhex("558bec"), bytes.fromhex("5589e5"))
PATCH = bytes.fromhex("31c0c3")
# CODOL_DeferConfigstringCommand entry located by the string xref and the
# enclosing GCC prologue in the shipped 2697 archive binary.
DEFAULT_ENTRY_VA = 0x47BB34


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_offset_to_va(pe, offset: int) -> int:
    base = pe.OPTIONAL_HEADER.ImageBase
    for section in pe.sections:
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        if start <= offset < end:
            return base + section.VirtualAddress + (offset - start)
    raise ValueError("offset outside every section")


def va_to_offset(pe, va: int) -> int:
    base = pe.OPTIONAL_HEADER.ImageBase
    rva = va - base
    for section in pe.sections:
        if section.VirtualAddress <= rva < section.VirtualAddress + section.Misc_VirtualSize:
            return section.PointerToRawData + (rva - section.VirtualAddress)
    raise ValueError("VA outside every section")


def find_function_entry(data: bytes, pe, reference_offset: int) -> int | None:
    """Walk backwards from a string xref to a known function prologue."""
    for pos in range(reference_offset, max(0, reference_offset - 0x1000), -1):
        if data[pos:pos + 3] in PROLOGUES:
            return pos
    return None


def analyze(path: Path, entry_va: int | None = None) -> dict:
    raw = path.read_bytes()
    pe = pefile.PE(str(path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    needle = STRING
    offset = raw.find(needle)
    if offset < 0:
        raise SystemExit("defer string not found")
    va = file_offset_to_va(pe, offset)
    result: dict = {"exe": str(path), "sha256": sha(path), "string_offset": hex(offset),
                    "string_va": hex(va), "references": [], "entry": None, "entry_offset": None}
    refs = []
    needle_va = struct.pack("<I", va)
    pos = 0
    while True:
        pos = raw.find(needle_va, pos)
        if pos < 0:
            break
        refs.append(pos)
        pos += 1
    result["references"] = [hex(r) for r in refs]
    if entry_va is not None:
        try:
            entry_offset = va_to_offset(pe, entry_va)
        except ValueError:
            entry_offset = None
        if entry_offset is not None:
            result["entry_offset"] = hex(entry_offset)
            result["entry"] = hex(entry_va)
            result["entry_bytes"] = raw[entry_offset:entry_offset + 8].hex()
    else:
        for ref in refs:
            entry = find_function_entry(raw, pe, ref)
            if entry is not None:
                result["entry_offset"] = hex(entry)
                result["entry"] = hex(file_offset_to_va(pe, entry))
                result["entry_bytes"] = raw[entry:entry + 8].hex()
                break
    pe.close()
    return result


def apply(path: Path, out: Path, entry_va: int) -> dict:
    info = analyze(path, entry_va)
    if info["entry_offset"] is None:
        raise SystemExit("entry not located")
    raw = bytearray(path.read_bytes())
    offset = int(info["entry_offset"], 16)
    before = bytes(raw[offset:offset + 3])
    raw[offset:offset + 3] = PATCH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(raw))
    info.update(out=str(out), out_sha256=sha(out), before=before.hex(),
                after=bytes(raw[offset:offset + 3]).hex(), patched=True)
    return info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--out", type=Path, default=Path(r"runs\dedrun-defer-patched.exe"))
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--entry-va", type=lambda value: int(value, 0), default=DEFAULT_ENTRY_VA)
    args = parser.parse_args()
    import json

    if args.apply:
        row = apply(args.exe, args.out, args.entry_va)
    else:
        row = analyze(args.exe, args.entry_va)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
