"""Probe an ff payload for a known compression stream.

The extracted mp_playlists.ff starts with IWff0100 and then looks like
high-entropy data, so try the usual suspects: raw zlib, gzip, LZMA, and a
zlib stream at a few offsets after the header.

    python tools/ff_decompress.py runtime/extracted/mp_playlists.ff
"""
from __future__ import annotations

import gzip
import lzma
import sys
import zlib
from pathlib import Path


def try_zlib(data: bytes, offset: int) -> tuple[bool, int, str]:
    try:
        out = zlib.decompressobj().decompress(data[offset:])
    except zlib.error as exc:
        return False, 0, str(exc)[:60]
    if len(out) > 32:
        return True, len(out), ""
    return False, len(out), "too small"


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                r"E:\GAME\COD\codol-airedux\319\runtime\extracted\mp_playlists.ff")
    data = path.read_bytes()
    print(f"{path.name}: {len(data):,} B")
    print(f"head: {data[:16].hex(' ')}")

    for name, fn in (("gzip", gzip.decompress), ("lzma", lzma.decompress)):
        try:
            out = fn(data)
            print(f"{name}: OK {len(out):,} B")
            Path(path.with_suffix(f".{name}.bin")).write_bytes(out)
            return 0
        except Exception as exc:  # noqa: BLE001 - probing many formats
            print(f"{name}: no ({type(exc).__name__})")

    for offset in (0x00, 0x08, 0x0C, 0x10, 0x20, 0x40, 0x80, 0x100):
        ok, size, why = try_zlib(data, offset)
        tag = f"zlib@{offset:#x}"
        if ok:
            print(f"{tag}: OK {size:,} B")
            out = zlib.decompressobj().decompress(data[offset:])
            Path(path.with_suffix(".zlib.bin")).write_bytes(out)
            print(f"  wrote {path.with_suffix('.zlib.bin')}")
            return 0
        print(f"{tag}: no ({why})")

    # show the header words to reason about the format
    import struct
    print("header words:")
    for i in range(0, min(0x40, len(data)), 4):
        if i + 4 <= len(data):
            val = struct.unpack_from("<I", data, i)[0]
            print(f"  +{i:#04x}  {val:#010x}  ({val})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
