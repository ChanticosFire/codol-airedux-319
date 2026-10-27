"""Decode the entity section of a 1649370 snapshot frame (diagnostic).

    python tools/decode_entities_1649370.py runs/r695-demo-outer/baseline-outer17-245.bin
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server1649370.entity_fields164 import ENTITY_FIELDS164, ENTITY_SENTINEL  # noqa: E402
from decode_ps_1649370 import MsgReader, read_gap, read_value  # noqa: E402


def read_index_code(m: MsgReader, last: int) -> int:
    if m.read_bits(1):
        return last + 1
    far = m.read_bits(1)
    if far:
        return m.read_bits(11)
    return last + m.read_bits(9)


def decode_frame(body: bytes) -> dict:
    m = MsgReader(body)
    m.read_byte()
    m.read_long()
    m.read_byte()
    m.read_byte()
    m.read_bits(1)
    # playerState section: skip it using the same walk as decode_ps
    from decode_ps_1649370 import read_gap as gap_ps  # noqa: F401
    if m.read_bits(1):
        last = m.read_bits(8) - 1
        index = -1
        while True:
            step = read_gap(m)
            index += step
            if index > last:
                break
            offset, bits, hint, words = __import__("server1649370.player_fields164", fromlist=["PLAYER_FIELDS164"]).PLAYER_FIELDS164[index]
            read_value(m, bits)
            if index == last:
                break
    # tail: seventeen zero gates in our own frames; real demo frames carry data,
    # so stop here unless the tail is all zero (safe subset).
    tail_start = (m.cursor, m.bit)
    zero_tail = True
    snapshot = (m.cursor, m.bit)
    for _ in range(17):
        if m.read_bits(1):
            zero_tail = False
            break
    m.cursor, m.bit = snapshot
    if not zero_tail:
        return {"tail_nonzero": True, "entity_start": None}
    result = {"tail_nonzero": False, "entities": [], "anim": m.read_bits(1),
              "actors": m.read_bits(1)}
    last_number = -1
    while True:
        number = read_index_code(m, last_number)
        if number == ENTITY_SENTINEL:
            break
        last_number = number
        present = m.read_bits(1)
        changed = m.read_bits(1)
        origin_baseline = m.read_bits(1)
        last_field = m.read_bits(6)
        entry = {"number": number, "present": present, "changed": changed,
                 "origin_baseline": origin_baseline, "last": last_field, "fields": {}}
        if not (present or changed):
            result["entities"].append(entry)
            continue
        fields = ENTITY_FIELDS164[0]
        read_gap(m, 3)
        word, human = read_value(m, fields[0][1])
        entry["fields"]["0"] = {"bits": fields[0][1], "word": word, "value": human}
        type_index = word
        previous = 0
        for _ in range(last_field):
            step = read_gap(m, 3)
            index = previous + step
            if index >= len(ENTITY_FIELDS164[type_index]):
                break
            offset, bits, hint, words = ENTITY_FIELDS164[type_index][index]
            word, human = read_value(m, bits)
            entry["fields"][str(index)] = {"offset": hex(offset), "bits": bits,
                                           "word": word, "value": human}
            previous = index
        result["entities"].append(entry)
    result["clients_bit"] = m.read_bits(1)
    result["glass_bit"] = m.read_bits(1)
    result["end_cursor"] = m.cursor
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("frame", type=Path)
    args = ap.parse_args()
    result = decode_frame(args.frame.read_bytes())
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
