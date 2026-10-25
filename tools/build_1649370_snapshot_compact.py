"""Build the 182-byte, fully parsed 1649370 snapshot with an empty entity table.

This is a diagnostic base for adding the local player's entity. The client
accepts every section without a stream error, but the empty table does not
make a controllable player.

    python tools/build_1649370_snapshot_compact.py \
        --source runs/demo-outer-exact/baseline-outer17-245.bin \
        --out runs/snap-ps0-empty-entity-compact.bin
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SOURCE_SHA256 = "6d03cde387571deb9362904055c3d69df54ab369ca0778218b8f507addb534a6"
PLAYER_STATE_VALUE_OFFSET = 0x43
TABLE_FLAG_BIT = 1382
TABLE_COUNT_BYTE = 177


class MessageCursor:
    """The two linked cursors used by 0x447190 and 0x66ED70."""

    def __init__(self, data: bytes, bit: int, byte: int):
        self.data = data
        self.bit = bit
        self.byte = byte

    def bit1(self) -> int:
        if self.bit & 7 == 0:
            self.bit = self.byte * 8
            self.byte += 1
        value = (self.data[self.bit >> 3] >> (self.bit & 7)) & 1
        self.bit += 1
        return value

    def byte1(self) -> int:
        value = self.data[self.byte]
        self.byte += 1
        return value


def build(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("source must be the exact 245-byte outer17 baseline")
    if source[PLAYER_STATE_VALUE_OFFSET] != 5 or len(source) != 245:
        raise ValueError("baseline field 83 does not have the expected value")

    result = bytearray(source[:TABLE_COUNT_BYTE])
    result[PLAYER_STATE_VALUE_OFFSET] = 0  # field 83, playerState offset +4
    result[TABLE_FLAG_BIT >> 3] |= 0xC0   # table present; 8-bit count form
    result.extend((
        0x00,  # byte 177: empty table count
        0x10,  # byte 178: entity terminator selector 14; next block empty
        0xFF,  # byte 179: actor empty-list flag/form and low 7 id bits
        0x0F,  # byte 180: high 4 id bits, sub4 empty, glass empty
        0x05,  # byte 181: svc_EOF
    ))
    verify(bytes(result))
    return bytes(result)


def verify(payload: bytes) -> None:
    if len(payload) != 182 or payload[PLAYER_STATE_VALUE_OFFSET] != 0:
        raise ValueError("unexpected snapshot size or player-state byte")
    cursor = MessageCursor(payload, bit=TABLE_FLAG_BIT, byte=TABLE_COUNT_BYTE)
    if [cursor.bit1(), cursor.bit1(), cursor.byte1()] != [1, 1, 0]:
        raise ValueError("entity table header does not decode as count 0")
    if (cursor.bit, cursor.byte) != (1384, 178):
        raise ValueError("entity table header cursor mismatch")
    # 0x471D80: explicit entity, followed by selector 14 (>12) to end list.
    if [cursor.bit1() for _ in range(6)] != [0, 0, 0, 0, 1, 0]:
        raise ValueError("entity-list terminator mismatch")
    if (cursor.bit, cursor.byte) != (1430, 179):
        raise ValueError("entity-list cursor mismatch")
    if cursor.bit1() != 0 or cursor.bit != 1431:
        raise ValueError("next block should be empty")
    if [cursor.bit1(), cursor.bit1()] != [0, 1]:
        raise ValueError("actor-list header mismatch")
    if sum(cursor.bit1() << bit for bit in range(11)) != 2047:
        raise ValueError("actor-list terminator mismatch")
    if (cursor.bit, cursor.byte) != (1444, 181):
        raise ValueError("actor-list cursor mismatch")
    if [cursor.bit1(), cursor.bit1(), cursor.byte1()] != [0, 0, 5]:
        raise ValueError("sub4, glass, or EOF mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.source.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    print(f"{args.out}: {len(payload)} bytes sha256={hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
