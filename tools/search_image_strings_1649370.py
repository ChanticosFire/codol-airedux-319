"""Search ASCII/UTF-16 strings inside a 1649370 image and report their VAs.

    python tools/search_image_strings_1649370.py cg_drawGun viewmodel
    python tools/search_image_strings_1649370.py --section .rdata "ammo"
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pefile

DEFAULT_IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("needles", nargs="+")
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--section", default=None, help="restrict to one section name")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--utf16", action="store_true", help="also search UTF-16LE")
    args = ap.parse_args()

    data = args.image.read_bytes()
    pe = pefile.PE(str(args.image), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = []
    for section in pe.sections:
        name = section.Name.decode(errors="replace").rstrip("\0")
        sections.append((name, base + section.VirtualAddress,
                         section.PointerToRawData, section.SizeOfRawData))

    for needle in args.needles:
        raw = needle.encode("ascii")
        found = 0
        print(f"\n== {needle!r}")
        for name, va, offset, size in sections:
            if args.section and name != args.section:
                continue
            blob = data[offset:offset + size]
            start = 0
            variants = [(raw, 1)]
            if args.utf16:
                variants.append((needle.encode("utf-16-le"), 2))
            for pattern, width in variants:
                while found < args.max:
                    index = blob.find(pattern, start)
                    if index < 0:
                        break
                    start = index + 1
                    address = va + index
                    context = blob[max(0, index - 16):index + 48]
                    context = context.split(b"\x00")[0]
                    print(f"  {address:#010x} [{name}/{width}] "
                          f"{context[:64]!r}")
                    found += 1
        if not found:
            print("  (not found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
