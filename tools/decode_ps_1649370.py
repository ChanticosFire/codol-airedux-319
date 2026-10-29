"""Decode the playerState section of a 1649370 snapshot (read side of wire164).

`server1649370/wire164.py` only writes.  Comparing our snapshots against the
2021 demos needs the opposite direction: read a frame, walk the descriptor
table and report the fields the sender actually changed.  The reader mirrors the
writer's dual-cursor semantics exactly (byte cursor for strings/whole bytes, bit
cursor for sub-byte fields).

    python tools/decode_ps_1649370.py runs/r681-weapon78-clip30-z220.bin
    python tools/decode_ps_1649370.py runs/r504-baseline.bin --json
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server1649370.player_fields164 import PLAYER_FIELDS164
from server1649370.event_fields164 import EVENT_PARAMETER_WIDTHS164
from server1649370.wire164 import TAIL_SECTIONS


class MsgReader:
    """Mirror of wire164.MsgWriter: one buffer, byte cursor plus bit cursor."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.cursor = 0
        self.bit = 0

    def read_data(self, count: int) -> bytes:
        blob = self.data[self.cursor:self.cursor + count]
        if len(blob) != count:
            raise EOFError("byte cursor past end")
        self.cursor += count
        return blob

    def read_byte(self) -> int:
        return self.read_data(1)[0]

    def read_long(self) -> int:
        return struct.unpack("<I", self.read_data(4))[0]

    def read_short(self) -> int:
        return struct.unpack("<H", self.read_data(2))[0]

    def read_bits(self, count: int) -> int:
        value = 0
        for index in range(count):
            if not (self.bit & 7):
                self.bit = self.cursor * 8
                if self.bit >= len(self.data) * 8:
                    raise EOFError("bit cursor past end")
                self.cursor += 1
            byte = self.data[self.bit >> 3]
            value |= ((byte >> (self.bit & 7)) & 1) << index
            self.bit += 1
        return value


def _word(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _real(word: int) -> float:
    return struct.unpack("<f", struct.pack("<I", word & 0xFFFFFFFF))[0]


def _mask(width: int) -> int:
    return 0xFFFFFFFF if width == 32 else (1 << width) - 1


def read_gap(m: MsgReader, chunk_bits: int = 4) -> int:
    if m.read_bits(1):
        return 1
    limit = (1 << chunk_bits) - 1
    distance = 1
    while True:
        part = m.read_bits(chunk_bits)
        distance += part
        if part != limit:
            return distance


def read_compressed(m: MsgReader, width: int) -> int:
    low = width & 7
    value = m.read_bits(low)
    rest = width - low
    shift = low
    while rest:
        value |= m.read_byte() << shift
        shift += 8
        rest -= 8
    return value


def read_value(m: MsgReader, bits: int, from_word: int = 0,
               position_base=(0.0, 0.0, 0.0)) -> tuple[int, float | None]:
    """Return (word, human value) for one descriptor codec, from a zero baseline."""
    if bits in (-92, -83, -91, -82, -90, -81):
        axis = 0 if bits in (-92, -83) else 1 if bits in (-91, -82) else 2
        gate = m.read_bits(1)
        raw = m.read_bits(16)
        if not gate:
            return 0, 0.0
        base = math.floor(position_base[axis] - 32768.0)
        word = _word(base + (raw ^ 0))
        return word, _real(word)
    if bits in (-100, -79):
        m.read_bits(2)
        raw = m.read_short()
        return _word(raw / 182.04444885253906), raw / 182.04444885253906
    if bits == -87:
        raw = m.read_short()
        return _word(raw / 182.04444885253906), raw / 182.04444885253906
    if bits in (-97, -74, -72, -70):
        gate = m.read_bits(1)
        if gate:
            return m.read_long(), None
        return m.read_bits(8), None
    if bits in (-80, -78, -73, -71):
        value = m.read_long()
        return value, float(value)
    if bits == -88:
        return m.read_long(), None
    if bits == -94:
        changed_id = m.read_bits(1)
        event_id = m.read_byte() if changed_id else 0
        if event_id >= len(EVENT_PARAMETER_WIDTHS164):
            raise ValueError("event ID exceeds verified Build 1649370 table")
        width = EVENT_PARAMETER_WIDTHS164[event_id]
        if not width:
            return event_id, 0
        if changed_id and not m.read_bits(1):
            return event_id, 0  # unchanged zero-baseline parameter
        return event_id, m.read_bits(width)
    if bits in (-93, -84):
        width = 11 if bits == -93 else 7
        return m.read_bits(width), None
    if bits == -65:
        return m.read_bits(10) * 100, None
    if bits == -86:
        return m.read_bits(6), m.read_bits(0) if False else None
    if bits == -96:
        if m.read_bits(1):
            return 2046, None
        if m.read_bits(1):
            return 0, None
        low = m.read_bits(3)
        return (m.read_byte() << 3) | low, None
    if bits == -98:
        m.read_bits(1)
        return m.read_bits(30), None
    if bits == -77:
        return read_compressed(m, 8), None
    if bits == -75:
        if m.read_bits(1):
            return m.read_bits(3) + 1, None
        return m.read_byte(), None
    if bits == -76:
        if m.read_bits(1):
            return m.read_bits(5) - 16, None
        return read_compressed(m, 8), None
    if bits == -85:
        if m.read_bits(1):
            return 0, None
        same = m.read_bits(1)
        rgb = 0
        if not same:
            rgb = m.read_byte() | (m.read_byte() << 8) | (m.read_byte() << 16)
        alpha = m.read_bits(5) << 3
        return (alpha << 24) | rgb, None
    if bits in (0, -89, -99):
        if bits == 0:
            if not m.read_bits(1):
                sign = m.read_bits(1)
                return (sign << 31), 0.0
            return read_compressed(m, 13), None
        if bits == -99:
            if not m.read_bits(1):
                return 0, 0.0
            return read_compressed(m, 12), None
        return read_compressed(m, 13), None
    if bits == -102:
        if not m.read_bits(1):
            return 0, None
        return m.read_bits(31), None
    if bits == -101:
        if not m.read_bits(1):
            return 0, None
        return m.read_bits(6), None
    if bits == -58:
        if m.read_bits(1):
            return m.read_long(), None
        return m.read_bits(2) * 10, None
    if bits == -57:
        return m.read_bits(1), None
    if bits == -55:
        raise NotImplementedError("-55 group codec is not modelled")
    # Every remaining descriptor is a positive/negative width integer, which the
    # writer emits as one presence bit followed by the compressed value.
    if not m.read_bits(1):
        return 0, None
    raw = read_compressed(m, abs(bits))
    if bits < 0 and raw & (1 << (abs(bits) - 1)):
        raw -= 1 << abs(bits)
    return raw & 0xFFFFFFFF, None


def decode_snapshot(body: bytes) -> dict:
    m = MsgReader(body)
    svc = m.read_byte()
    server_time = m.read_long()
    delta = m.read_byte()
    flags = m.read_byte()
    has_base = m.read_bits(1)
    result = {"svc": svc, "server_time": server_time, "delta": delta,
              "flags": flags, "has_base": has_base, "fields": {}, "tail": {}}
    if not m.read_bits(1):
        result["ps_present"] = False
        return result
    last = m.read_bits(8) - 1
    result["last"] = last
    index = -1
    while True:
        gap = read_gap(m)
        index += gap
        if index > last:
            break
        if index >= len(PLAYER_FIELDS164):
            break
        offset, bits, hint, words = PLAYER_FIELDS164[index]
        try:
            word, human = read_value(m, bits)
        except Exception as error:  # noqa: BLE001 - diagnostic path
            result["error"] = {"index": index, "offset": hex(offset), "bits": bits,
                               "byte_cursor": m.cursor, "bit_cursor": m.bit,
                               "message": repr(error)}
            return result
        result["fields"][hex(offset)] = {"index": index, "bits": bits,
                                         "word": word, "value": human}
        if bits == -94:
            result["fields"][hex(offset)]["event_parameter"] = human
        if index == last:
            break
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("frame", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    body = args.frame.read_bytes()
    result = decode_snapshot(body)
    if args.json:
        print(json.dumps(result, indent=1))
        return 0
    print(f"svc={result['svc']} server_time={result['server_time']} "
          f"delta={result['delta']} flags={result['flags']} last={result.get('last')}")
    for offset, info in sorted(result["fields"].items(),
                               key=lambda kv: kv[1]["index"]):
        print(f"  {offset:>6} idx={info['index']:>3} bits={info['bits']:>4} "
              f"word={info['word']:#010x} value={info['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
