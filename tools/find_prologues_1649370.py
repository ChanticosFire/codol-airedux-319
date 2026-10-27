"""List candidate function prologues (`55 8b ec`) inside a VA range.

Linear sweeps are good for xrefs but they cannot answer "where does this
function start".  This tool walks the raw image bytes for the standard MSVC
frame-pointer prologue and reports each hit with the byte before it, so
padding (`cc`) and real code are distinguishable.

    python tools/find_prologues_1649370.py 0x58f700 0x58fe00
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pefile

DEFAULT_IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("start", type=lambda text: int(text, 0))
    ap.add_argument("end", type=lambda text: int(text, 0))
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    args = ap.parse_args()

    data = args.image.read_bytes()
    pe = pefile.PE(str(args.image), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    for section in pe.sections:
        va = base + section.VirtualAddress
        raw = section.PointerToRawData
        size = section.SizeOfRawData
        if va <= args.start < va + size:
            offset = raw + (args.start - va)
            blob = data[offset:offset + (args.end - args.start)]
            break
    else:
        raise SystemExit("start VA is outside every section")

    hits = 0
    for index in range(len(blob) - 2):
        if blob[index:index + 3] == b"\x55\x8b\xec":
            va = args.start + index
            previous = blob[index - 1] if index else None
            payload = blob[index:index + 12].hex(" ")
            print(f"{va:#010x} prev={previous if previous is None else hex(previous)} {payload}")
            hits += 1
    print(f"hits={hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
