"""Small 1649370 initial-state producer using the client's recovered layout.

Message semantics (verified against the 1649370 client parser at 0x472D80):

* the message is an interleaved byte/bit stream.  ``WriteBits`` reserves a
  byte at the byte cursor the first time a bit is written on a fresh byte and
  keeps filling that byte while strings are appended at the end of the
  message.  The reader keeps the same two independent cursors, so a string
  never moves the bit cursor in the middle of a reserved byte.
* the text configstring table starts with ``04`` + u16 count, then per entry
  one incremental bit (``1`` == previous + 1) or ``0`` + 14-bit index, then a
  NUL terminated string.
* the client rejects an entry whose slot type at ``0x77D8250+index`` is below
  0x17 and not 0x15; unset slots read 0xFF and are accepted as text.

The 84-byte probe only carried slot 0.  The client's map-loading pass compares
slot 2 with the literal ``cod`` (0x4549F0..0x454A28) and raises
``Com_Error(2, "\\x15186 %s %s", "cod", actual)`` when it differs.  Slot 2 is
therefore sent as ``cod`` here; slot 1 stays empty until its consumer is known.
"""
from __future__ import annotations

import struct

TEXT_CONFIGSTRING_TYPE_MIN = 0x17
TEXT_CONFIGSTRING_TYPE_ALT = 0x15
CONFIGSTRING_COUNT_MAX = 0x31D9
CONFIGSTRING_INDEX_BITS = 14

DEFAULT_CONFIGSTRINGS: tuple[tuple[int, bytes], ...] = (
    (0, b"\\g_gametype\\war\\mapname\\mp_cross_fire"),
    (1, b""),
    (2, b"cod"),
)


class Writer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.bit = 0

    def raw(self, data: bytes) -> None:
        self.data.extend(data)

    def bits(self, value: int, width: int) -> None:
        if value < 0 or value >= 1 << width:
            raise ValueError(f"{value} does not fit in {width} bits")
        for shift in range(width):
            if self.bit & 7 == 0:
                self.bit = len(self.data) * 8
                self.data.append(0)
            self.data[self.bit >> 3] |= ((value >> shift) & 1) << (self.bit & 7)
            self.bit += 1

    def string(self, value: bytes) -> None:
        if b"\0" in value:
            raise ValueError("string contains NUL")
        self.raw(value + b"\0")


def _validated(entries) -> list[tuple[int, bytes]]:
    rows: list[tuple[int, bytes]] = []
    previous = -1
    for index, value in entries:
        if not isinstance(value, (bytes, bytearray)):
            raise TypeError("configstring values must be bytes")
        value = bytes(value)
        if not 0 <= index < CONFIGSTRING_COUNT_MAX:
            raise ValueError(f"configstring index {index} outside 0..{CONFIGSTRING_COUNT_MAX - 1}")
        if index <= previous:
            raise ValueError("configstring indices must be strictly increasing")
        if b"\0" in value:
            raise ValueError(f"configstring {index} contains NUL")
        rows.append((index, value))
        previous = index
    if len(rows) > CONFIGSTRING_COUNT_MAX:
        raise ValueError("too many configstrings")
    return rows


def build_native_gamestate(registration_checksum: int, *, checksum_feed: int = 0x1649370,
                           client_number: int = 0,
                           configstrings=DEFAULT_CONFIGSTRINGS) -> bytes:
    """Return plaintext after netchan sequence, including the 4-byte ack field."""
    if not 0 <= registration_checksum <= 0xFFFFFFFF:
        raise ValueError("registration checksum must be uint32")
    if not 0 <= checksum_feed <= 0xFFFFFFFF:
        raise ValueError("checksum feed must be uint32")
    if not 0 <= client_number < 19:
        raise ValueError("client number must be 0..18")
    rows = _validated(configstrings)
    writer = Writer()
    writer.raw(struct.pack("<I", 0))  # reliable command acknowledgement
    writer.raw(b"\x03")               # svc: initial state
    writer.raw(struct.pack("<I", 0))  # server command sequence
    writer.string(b"mp_cross_fire")
    writer.string(b"mp")
    writer.raw(struct.pack("<I", registration_checksum))
    writer.raw(b"\x04")               # svc: configstrings
    writer.raw(struct.pack("<H", len(rows)))
    previous = -1
    for index, value in rows:
        if index == previous + 1:
            writer.bits(1, 1)
        else:
            writer.bits(0, 1)
            writer.bits(index, CONFIGSTRING_INDEX_BITS)
        writer.string(value)
        previous = index
    # The client continues with two bit-packed weapon tables inside the same
    # configstring block: 10-bit alias count, then 11-bit recipe count.  Zero
    # counts are valid and keep the parser from reading the trailing payload as
    # thousands of records (which used to overflow the 0x20000 string pool).
    writer.bits(0, 10)
    writer.bits(0, 11)
    writer.raw(b"\x05")               # close configstring block
    writer.raw(struct.pack("<II", client_number, checksum_feed))
    writer.raw(b"\x05")               # close initial state
    return bytes(writer.data)


class Reader:
    """Offline mirror of the client's interleaved byte/bit reader."""

    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.cursor = offset
        self.bit = offset * 8

    def bits(self, width: int) -> int:
        value = 0
        for shift in range(width):
            if self.bit & 7 == 0:
                self.bit = self.cursor * 8
                self.cursor += 1
            value |= ((self.data[self.bit >> 3] >> (self.bit & 7)) & 1) << shift
            self.bit += 1
        return value

    def string(self) -> bytes:
        out = bytearray()
        while True:
            value = self.data[self.cursor]
            self.cursor += 1
            if not value:
                return bytes(out)
            out.append(value)


def parse_native_gamestate(payload: bytes) -> dict:
    """Parse a payload produced by build_native_gamestate; raises on mismatch."""
    if len(payload) < 33 or payload[4] != 3:
        raise ValueError("not a native gamestate")
    reader = Reader(payload, 5)
    sequence = int.from_bytes(payload[5:9], "little")
    reader.cursor = 9
    mapname = reader.string()
    gametype = reader.string()
    checksum = int.from_bytes(payload[reader.cursor:reader.cursor + 4], "little")
    reader.cursor += 4
    reader.bit = reader.cursor * 8
    if payload[reader.cursor] != 4:
        raise ValueError("missing configstring block")
    reader.cursor += 1
    count = int.from_bytes(payload[reader.cursor:reader.cursor + 2], "little")
    reader.cursor += 2
    previous = -1
    rows = []
    for _ in range(count):
        if reader.bits(1):
            index = previous + 1
        else:
            index = reader.bits(CONFIGSTRING_INDEX_BITS)
        value = reader.string()
        rows.append((index, value))
        previous = index
    alias_count = reader.bits(10)
    recipe_count = reader.bits(11)
    return {"sequence": sequence, "mapname": mapname, "gametype": gametype,
            "registration_checksum": checksum, "configstrings": rows,
            "alias_count": alias_count, "recipe_count": recipe_count,
            "after_configstrings": reader.cursor}
