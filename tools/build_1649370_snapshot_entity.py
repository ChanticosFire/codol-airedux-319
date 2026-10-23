"""Hand-build a 1649370 snapshot body with an explicit entity table.

Format recovered from the client parser:

    00                          svc_snapshot
    u32 serverTime              read with a 4-byte block reader (0x66E760)
    u8  delta                   byte cursor
    u8  snapFlags               byte cursor (0x0C = the value our baseline uses)
    -- bit stream from here --
    1   hasBase                 0x47238C
    entity table (0x671650): 1 bit (table), 1 bit (form), u8 count,
                             then 12 bits per entity id
    entity fields (0x671700)  per entity
    empty sub-blocks          (actor/sub4/glass encodings copied from the verified baseline)
    05                          svc_EOF

Usage:
    python tools/build_1649370_snapshot_entity.py --out runs/snapshot-empty-entity-table.bin
"""
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

SERVER_TIME = 72192
SNAP_FLAGS = 0x0C


class BitWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.bit = 0

    def raw(self, payload: bytes) -> None:
        self.data.extend(payload)

    def bits(self, value: int, width: int) -> None:
        if value < 0 or value >= 1 << width:
            raise ValueError(f"{value} does not fit in {width} bits")
        for shift in range(width):
            if self.bit & 7 == 0:
                self.bit = len(self.data) * 8
                self.data.append(0)
            self.data[self.bit >> 3] |= ((value >> shift) & 1) << (self.bit & 7)
            self.bit += 1


def build(*, server_time: int = SERVER_TIME, entity_ids: tuple[int, ...] = (),
          has_base: int = 0, flags: int = SNAP_FLAGS,
          ps_entries: int = 1) -> bytes:
    writer = BitWriter()
    writer.raw(b"\x00")
    writer.raw(struct.pack("<I", server_time))
    writer.raw(bytes([0, flags]))
    writer.bits(has_base & 1, 1)
    writer.bits(1, 1)                      # entity table present
    writer.bits(len(entity_ids), 8)
    for entity_id in entity_ids:
        writer.bits(entity_id, 12)
    if ps_entries:
        writer.bits(1, 1)                  # playerState block present (0x471A3E)
        writer.bits(0, 1)                  # five-bit count form (0x471A4D)
        writer.bits(ps_entries, 5)
        for _ in range(ps_entries):
            writer.bits(0, 1)              # field data present (0x471B9E)
            for _ in range(8):             # 0xDA63E8 lists eight playerState fields
                writer.bits(0, 1)
    # Empty actor / sub / glass blocks, matching the verified baseline's tail.
    writer.bits(0, 1)
    writer.bits(1, 1)
    writer.bits(2047, 11)
    writer.bits(0, 1)
    writer.bits(0, 1)
    writer.raw(b"\x05")
    return bytes(writer.data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/snapshot-empty-entity-table.bin"))
    parser.add_argument("--server-time", type=int, default=SERVER_TIME)
    parser.add_argument("--has-base", type=int, default=0)
    parser.add_argument("--entity", type=int, action="append", default=[],
                        help="entity id to include (repeatable)")
    args = parser.parse_args()
    payload = build(server_time=args.server_time, entity_ids=tuple(args.entity), has_base=args.has_base)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    print(f"wrote {args.out} ({len(payload)} bytes) sha256={hashlib.sha256(payload).hexdigest()}")
    print(f"entities={list(args.entity)} head={payload[:12].hex(' ')} tail={payload[-8:].hex(' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
