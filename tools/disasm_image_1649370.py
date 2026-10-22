"""Static VA-range disassembler for the exact 1649370 offline image.

Reads the file (never the process) and maps PE RVAs to raw offsets so every
byte shown is the shipped image content. Use it for repeatable function
dumps in evidence instead of ad-hoc Capstone snippets.

    python tools/disasm_image_1649370.py 0x6750A0 0x120
    python tools/disasm_image_1649370.py 0x5C0F50 0x180 --stop-ret 0
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import capstone
import pefile

DEFAULT_IMAGE = Path(
    r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
)
EXPECTED_SHA256 = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"


def load_sections(image: Path):
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    pe = pefile.PE(str(image), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = []
    for section in pe.sections:
        name = section.Name.decode(errors="replace").rstrip("\0")
        sections.append(
            {
                "name": name,
                "va": base + section.VirtualAddress,
                "vsize": section.Misc_VirtualSize,
                "raw": section.PointerToRawData,
                "rawsize": section.SizeOfRawData,
            }
        )
    return digest, base, sections


def read_va(data: bytes, sections, va: int, size: int) -> bytes:
    for section in sections:
        if section["va"] <= va < section["va"] + section["vsize"]:
            offset = va - section["va"]
            if offset + size > section["rawsize"]:
                size = section["rawsize"] - offset
            start = section["raw"] + offset
            return data[start:start + size]
    raise SystemExit(f"VA {va:#x} is outside every section")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("va", type=lambda text: int(text, 0))
    parser.add_argument("size", type=lambda text: int(text, 0))
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument(
        "--stop-ret",
        type=int,
        default=1,
        help="stop after this many ret instructions (0 = never)",
    )
    parser.add_argument("--raw", action="store_true", help="also show raw bytes")
    args = parser.parse_args()

    digest, base, sections = load_sections(args.image)
    data = args.image.read_bytes()
    blob = read_va(data, sections, args.va, args.size)
    print(f"image={args.image}")
    print(f"sha256={digest} expected_match={digest == EXPECTED_SHA256}")
    print(f"image_base={base:#x} va={args.va:#x} bytes={len(blob)}")
    if args.raw:
        print(f"raw={blob.hex()}")

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = False
    returns = 0
    consumed = 0
    for insn in md.disasm(blob, args.va):
        print(f"{insn.address:#010x}  {insn.bytes.hex(' '):<24} {insn.mnemonic} {insn.op_str}")
        consumed += insn.size
        if insn.mnemonic.startswith("ret"):
            returns += 1
            if args.stop_ret and returns >= args.stop_ret:
                break
    if consumed < len(blob):
        print(f"# disassembly ended at {args.va + consumed:#x} ({consumed}/{len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
