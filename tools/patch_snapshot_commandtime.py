"""Patch the snapshot's playerState commandTime field.

CL_PredictMovement compares the client's command times against the snapshot's
playerState; a commandTime of 0 makes every prediction look stale.  In this
build the snapshot header is a bit stream and commandTime is 4 bytes little
endian starting at bit 68 (after 1 bit no-prior-ps, 1 bit transmit origin, 8 bits
last_changed, 1 bit gap and 1 bit -97 codec).

    python tools/patch_snapshot_commandtime.py --in runs/snap.bin --out runs/snap-ct.bin --value 471192
"""
from __future__ import annotations

import argparse
from pathlib import Path

COMMAND_TIME_BIT = 68


def bit(blob: bytes, index: int) -> int:
    return (blob[index >> 3] >> (index & 7)) & 1


def set_bits(blob: bytearray, start: int, value: int, count: int) -> None:
    for i in range(count):
        index = start + i
        current = (blob[index >> 3] >> (index & 7)) & 1
        want = (value >> i) & 1
        if current != want:
            blob[index >> 3] ^= 1 << (index & 7)


def read_field(blob: bytes, start: int, count: int) -> int:
    value = 0
    for i in range(count):
        value |= bit(blob, start + i) << i
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", type=Path, required=True)
    parser.add_argument("--out", dest="dst", type=Path, required=True)
    parser.add_argument("--value", type=int, required=True)
    args = parser.parse_args()
    data = bytearray(args.src.read_bytes())
    before = read_field(data, COMMAND_TIME_BIT, 32)
    set_bits(data, COMMAND_TIME_BIT, args.value & 0xFFFFFFFF, 32)
    after = read_field(data, COMMAND_TIME_BIT, 32)
    args.dst.write_bytes(data)
    changed = sum(1 for a, b in zip(args.src.read_bytes(), data) if a != b)
    print(f"{args.dst}: {len(data)} bytes, commandTime {before} -> {after}, {changed} byte(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
