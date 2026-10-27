"""Read C strings / raw dwords out of a 1649370 image by VA.

Static evidence needs the shipped bytes, not a decompiler's opinion.

    python tools/read_image_strings_1649370.py 0xdbf030 0xdbf058
    python tools/read_image_strings_1649370.py 0x1988b50 --dwords 8
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pefile

DEFAULT_IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", type=lambda text: int(text, 0))
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--dwords", type=int, default=0, help="read this many dwords instead of a string")
    ap.add_argument("--max-bytes", type=int, default=512)
    args = ap.parse_args()

    data = args.image.read_bytes()
    pe = pefile.PE(str(args.image), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = [(base + s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData)
                for s in pe.sections]

    def read(va: int, size: int):
        for start, raw, rawsize in sections:
            if start <= va < start + rawsize:
                offset = raw + (va - start)
                return data[offset:offset + size]
        return None

    for target in args.targets:
        blob = read(target, args.max_bytes)
        if blob is None:
            print(f"{target:#x}: outside every section")
            continue
        if args.dwords:
            words = [int.from_bytes(blob[i:i + 4], "little") for i in range(0, 4 * args.dwords, 4)]
            print(f"{target:#x}: " + " ".join(f"{w:#010x}" for w in words))
        else:
            text = blob.split(b"\x00")[0]
            print(f"{target:#x}: {text!r}  (len={len(text)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
