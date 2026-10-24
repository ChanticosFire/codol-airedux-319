"""Read a VA string / u32 from the shipped 1649370 image (file-based, no process)."""
from __future__ import annotations

import struct
import sys

import pefile

IMAGE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(IMAGE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
raw = open(IMAGE, "rb").read()


def read_va(va: int, size: int) -> bytes:
    for s in pe.sections:
        start = base + s.VirtualAddress
        if start <= va < start + s.Misc_VirtualSize:
            off = va - start
            return raw[s.PointerToRawData + off:s.PointerToRawData + off + size]
    raise SystemExit(f"VA {va:#x} outside sections")


def cstr(va: int, limit: int = 200) -> str:
    data = read_va(va, limit)
    end = data.find(b"\0")
    return data[:end if end >= 0 else limit].decode("latin-1")


for arg in sys.argv[1:]:
    va = int(arg, 0)
    print(f"{va:#x}: {cstr(va)!r}")
