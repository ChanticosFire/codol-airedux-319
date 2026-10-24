"""Rebuild a zone blob, optionally appending assets from another zone.

    python tools/zone_merge.py --base runs/ff-decoded/common --out runs/ff-edit/common.zone
    python tools/zone_merge.py --base ... --add runs/ff-decoded/gametype --indices 47,48 --out ...

Zone layout (verified against fastfile.validate_zone):
    0x00 u32 size            (= len(zone) - 0x28)
    0x28 u32 string_count
    0x30 u32 asset_count
    0x38 string table        (string_count * 4 bytes, copied verbatim)
         asset directory     (asset_count * 16B {type, offset, pointer, extent})
         asset data          (contiguous; entry.offset + 0x28 == position)

`offset` on disk is stored relative to the 0x28 header slice, hence the +0x28.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"E:\GAME\COD\1649370\src")
from codol_rebuild.resources.fastfile import validate_zone  # noqa: E402

HEADER = 0x38


class Zone:
    def __init__(self, blob: bytes) -> None:
        info = validate_zone(blob)
        self.count = info["asset_count"]
        self.string_count = info["string_count"]
        dir_off = info["directory_offset"]
        self.block_sizes = blob[0x04:0x24]   # 8 * u32, kept verbatim
        self.strings = blob[HEADER:dir_off]
        self.meta = [(e["type"], e["pointer"]) for e in info["asset_entries"]]
        self.blobs = [blob[e["offset"]:e["offset"] + e["size"]] for e in info["asset_entries"]]

    def rebuild(self) -> bytes:
        count = len(self.blobs)
        head = HEADER + len(self.strings) + count * 16
        offsets = []
        cursor = head
        for blob in self.blobs:
            offsets.append(cursor)
            cursor += len(blob)
        total = cursor
        out = bytearray(total)
        struct.pack_into("<I", out, 0x00, total - 0x28)
        struct.pack_into("<I", out, 0x28, self.string_count)
        struct.pack_into("<I", out, 0x30, count)
        out[0x04:0x24] = self.block_sizes
        out[HEADER:HEADER + len(self.strings)] = self.strings
        pos = HEADER + len(self.strings)
        for index, offset in enumerate(offsets):
            kind, pointer = self.meta[index]
            struct.pack_into("<4I", out, pos, kind, offset - 0x28, pointer, len(self.blobs[index]))
            pos += 16
        out[head:] = b"".join(self.blobs)
        return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--add")
    ap.add_argument("--indices", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    zone = Zone(Path(args.base).read_bytes())
    before = len(zone.blobs)
    if args.add:
        extra = Zone(Path(args.add).read_bytes())
        wanted = {int(x) for x in args.indices.split(",") if x.strip()}
        if not wanted:
            raise SystemExit("--indices required with --add")
        for index in sorted(wanted):
            zone.meta.append((extra.meta[index][0], 0xFFFFFFFF))
            zone.blobs.append(extra.blobs[index])
    blob = zone.rebuild()
    info = validate_zone(blob)  # raises if the rebuild is inconsistent
    Path(args.out).write_bytes(blob)
    print(f"base={before} added={len(zone.blobs) - before} total={info['asset_count']} "
          f"size={len(blob)} strings={info['string_count']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
