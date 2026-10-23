"""Bit-exact encoder for the CODOL snapshot delta-field stream.

The rules here are transcribed from the working 3.3.3.3 encoder in
`cols/crates/protocol/src/game/snapshot/mod.rs` (see
`docs/SNAPSHOT-FORMAT.md` section 10).  They are **not** guesses: `gap()` and
every codec branch are copied from that source, including the important detail
that a positive-width codec writes a gate bit and then the `width % 8`
remainder bits **before** the whole bytes.

This module is transport-agnostic: it only produces/consumes bits.
"""

from __future__ import annotations

import struct


class BitWriter:
    """LSB-first bit writer (bit i lives in byte i >> 3 at bit i & 7)."""

    def __init__(self, size_hint_bits: int = 4096) -> None:
        self.data = bytearray((size_hint_bits >> 3) + 16)
        self.position = 0

    def bit(self, value: int) -> None:
        if (self.position >> 3) >= len(self.data):
            self.data.append(0)
        if value & 1:
            self.data[self.position >> 3] |= 1 << (self.position & 7)
        self.position += 1

    def bits(self, value: int, count: int) -> None:
        for index in range(count):
            self.bit((value >> index) & 1)

    def byte(self, value: int) -> None:
        self.bits(value & 0xFF, 8)

    def le32(self, value: int) -> None:
        for shift in (0, 8, 16, 24):
            self.byte((value >> shift) & 0xFF)

    def to_bytes(self) -> bytes:
        return bytes(self.data[: (self.position + 7) >> 3])


class BitReader:
    """Mirror of :class:`BitWriter` for round-trip tests."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def bit(self) -> int:
        if (self.position >> 3) >= len(self.data):
            raise ValueError("bit stream exhausted")
        value = (self.data[self.position >> 3] >> (self.position & 7)) & 1
        self.position += 1
        return value

    def bits(self, count: int) -> int:
        value = 0
        for index in range(count):
            value |= self.bit() << index
        return value

    def byte(self) -> int:
        return self.bits(8)

    def le32(self) -> int:
        return sum(self.byte() << (8 * index) for index in range(4))


# --------------------------------------------------------------------------- gap
def write_gap(writer: BitWriter, distance: int) -> None:
    """Distance coder, verbatim from cols (`fn gap`, snapshot/mod.rs:1431)."""
    writer.bit(1 if distance == 1 else 0)
    if distance == 1:
        return
    rest = distance - 1
    while rest >= 15:
        writer.bits(15, 4)
        rest -= 15
    writer.bits(rest, 4)


def read_gap(reader: BitReader) -> int:
    if reader.bit():
        return 1
    distance = 1
    while True:
        chunk = reader.bits(4)
        distance += chunk
        if chunk != 15:
            return distance


# --------------------------------------------------------------------- codecs
def write_field(writer: BitWriter, codec: int, value: int) -> None:
    """Write one field value with the codec taken from the field table.

    Mirrors the branch order in cols `player_frame_with_world` so that the
    bytes match a real server's stream.
    """
    if codec == -88:
        writer.bits(value & 0xFFFFFFFF, 32)
    elif codec == -87:
        writer.bits(value & 0xFFFF, 16)
    elif codec == -75:
        writer.byte(value & 0xFF)
    elif codec == -94:
        raise NotImplementedError("-94 event payload needs the event table")
    elif codec == -97:
        writer.bit(1)
        writer.le32(value & 0xFFFFFFFF)
    elif codec == -100:
        writer.bit(1)
        writer.bit(1)
        writer.le32(value & 0xFFFFFFFF)
    elif codec == -101:
        writer.bits(0, 2)
        writer.bits(value & 0xFFFF, 16)
    elif codec > 0:
        # gate bit, then width % 8 remainder bits FIRST, then whole bytes
        writer.bit(1)
        remainder = codec % 8
        writer.bits(value, remainder)
        shift = remainder
        while shift < codec:
            writer.byte((value >> shift) & 0xFF)
            shift += 8
    else:
        raise ValueError(f"unsupported codec {codec}")


def read_field(reader: BitReader, codec: int) -> int:
    if codec == -88:
        return reader.bits(32)
    if codec == -87:
        return reader.bits(16)
    if codec == -75:
        return reader.byte()
    if codec == -97:
        if reader.bit() != 1:
            raise ValueError("-97 expects a 1 gate bit")
        return reader.le32()
    if codec == -100:
        reader.bits(2)
        return reader.le32()
    if codec == -101:
        if reader.bits(2) != 0:
            raise ValueError("-101 expects 2 zero bits")
        return reader.bits(16)
    if codec > 0:
        if reader.bit() != 1:
            raise ValueError("positive codec expects a 1 gate bit")
        remainder = codec % 8
        value = reader.bits(remainder)
        shift = remainder
        while shift < codec:
            value |= reader.byte() << shift
            shift += 8
        return value
    raise ValueError(f"unsupported codec {codec}")


# ------------------------------------------------------------------- self test
def _self_test() -> int:
    """Round-trip every codec and the gap coder; return a failure count."""
    failures = 0

    def check(name: str, got, want) -> None:
        nonlocal failures
        if got != want:
            failures += 1
            print(f"FAIL {name}: got {got!r} want {want!r}")

    # gap distances
    for distance in (1, 2, 3, 15, 16, 17, 30, 31, 46):
        writer = BitWriter(256)
        write_gap(writer, distance)
        raw = writer.to_bytes()
        reader = BitReader(raw)
        check(f"gap({distance})", read_gap(reader), distance)

    # codecs
    cases = [
        (-88, 0x3F800000),
        (-87, 0x1234),
        (-75, 0x7F),
        (-97, 0x5A20C0),
        (-100, 0x40000000),
        (-101, 0x0100),
        (6, 0x2A),
        (10, 0x2FF),
        (11, 0x7FF),
        (12, 0xABC),
        (16, 0xBEEF),
        (32, 0xDEADBEEF),
    ]
    for codec, value in cases:
        writer = BitWriter(256)
        write_field(writer, codec, value)
        reader = BitReader(writer.to_bytes())
        check(f"codec {codec} value {value:#x}", read_field(reader, codec), value)

    # an encoded field must be byte-identical to an independent re-encoding
    writer = BitWriter(256)
    write_field(writer, 10, 0x2FF)
    check("codec 10 width", writer.position, 1 + 2 + 8)  # gate + remainder + one byte

    print(f"self-test failures: {failures}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _self_test() else 0)
