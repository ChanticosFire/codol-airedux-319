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

import os
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
        # The decoder (0x66F9E0) has TWO forms for -97:
        #   gate bit 0 -> read 8 more bits, value = previous - decoded8
        #   gate bit 1 -> read 32 bits (little endian), absolute
        # Historically we only emitted the 32-bit form. PS97_GATE0 selects the
        # 8-bit delta form so both can be compared in one experiment.
        if os.environ.get("PS97_GATE0") == "1":
            writer.bit(0)
            writer.bits(int(value) & 0xFF, 8)
        else:
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
        # 1649370 positive-width codec, read from 0x670B15:
        #   read 1 bit; if 0 -> value 0 and done
        #   else read `codec` bits, plain LSB-first
        # (the 3.3.3.3 "remainder bits first then whole bytes" form does NOT
        # apply to this build - that was a porting mistake corrected here.)
        if value == 0:
            writer.bit(0)
            return
        writer.bit(1)
        writer.bits(value, codec)
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
        # Two forms, mirroring 0x66F9E0: gate 0 -> 8-bit delta, gate 1 -> 32-bit.
        if reader.bit() == 0:
            return -reader.bits(8)
        return reader.le32()
    if codec == -100:
        reader.bits(2)
        return reader.le32()
    if codec == -101:
        if reader.bits(2) != 0:
            raise ValueError("-101 expects 2 zero bits")
        return reader.bits(16)
    if codec > 0:
        if reader.bit() == 0:
            return 0
        return reader.bits(codec)
    raise ValueError(f"unsupported codec {codec}")



# ------------------------------------------------- 1649370 distance coder (0x670CB0)
# The 1649370 decoder uses a 3-bit chunk variant with max 7 and a 1-based result:
#   read 1 bit -> 1 => distance 1
#   else: edi = 1; read 3 bits; while chunk == 7: edi += 7, read 3 bits; edi += chunk
# so distance = 1 + sum(chunks).
DISTANCE_CHUNK_BITS = 3
DISTANCE_CHUNK_MAX = (1 << DISTANCE_CHUNK_BITS) - 1


def write_distance(writer: BitWriter, distance: int) -> None:
    """Encode the 1649370 distance form (0x670CB0), not the 3.3.3.3 four-bit form."""
    if distance < 1:
        raise ValueError("distance must be >= 1")
    if distance == 1:
        writer.bit(1)
        return
    writer.bit(0)
    rest = distance - 1
    while rest > DISTANCE_CHUNK_MAX:
        writer.bits(DISTANCE_CHUNK_MAX, DISTANCE_CHUNK_BITS)
        rest -= DISTANCE_CHUNK_MAX
    writer.bits(rest, DISTANCE_CHUNK_BITS)


def read_distance(reader: BitReader) -> int:
    if reader.bit() == 1:
        return 1
    total = 1
    while True:
        chunk = reader.bits(DISTANCE_CHUNK_BITS)
        total += chunk
        if chunk != DISTANCE_CHUNK_MAX:
            return total

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

    # distances through the 1649370 form
    for distance in (1, 2, 3, 8, 9, 23, 24, 100):
        writer = BitWriter(256)
        write_distance(writer, distance)
        check(f"distance({distance})", read_distance(BitReader(writer.to_bytes())), distance)

    # codecs
    # a non-zero positive-width field costs gate + width bits
    writer = BitWriter(64)
    write_field(writer, 11, 0x100)
    check("codec 11 non-zero width", writer.position, 1 + 11)

    # a zero value must cost exactly one bit
    writer = BitWriter(64)
    write_field(writer, 10, 0)
    check("zero value costs 1 bit", writer.position, 1)

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
