"""Inspect only the verified prefix of the captured configstring stream.

The 1649370 client reads a u16 text count at plaintext offset 31. Bit reads
retain their partial byte while NUL-terminated strings advance the byte cursor.
The 2697 stream diverges later; this probe deliberately stops after three items.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


class Reader:
    def __init__(self, data: bytes, offset: int):
        self.data = data
        self.byte = offset
        self.bit = offset * 8

    def raw(self, size: int) -> bytes:
        end = self.byte + size
        if end > len(self.data):
            raise ValueError(f"truncated at byte {self.byte}")
        value = self.data[self.byte:end]
        self.byte = end
        return value

    def u16(self) -> int:
        return int.from_bytes(self.raw(2), "little")

    def bits(self, width: int) -> int:
        value = 0
        for shift in range(width):
            if self.bit & 7 == 0:
                self.bit = self.byte * 8
                self.raw(1)
            value |= ((self.data[self.bit >> 3] >> (self.bit & 7)) & 1) << shift
            self.bit += 1
        return value

    def string(self) -> bytes:
        out = bytearray()
        while True:
            value = self.raw(1)[0]
            if not value:
                return bytes(out)
            out.append(value)


def inspect(payload: bytes, types: bytes, max_entries: int = 3) -> dict:
    if len(types) != 12761:
        raise ValueError("1649370 slot type table must have 12761 bytes")
    reader = Reader(payload, 31)
    count = reader.u16()
    if count > len(types):
        raise ValueError(f"text count {count} exceeds native slot count")
    previous = None
    entries = []
    parse_error = None
    for number in range(min(count, max_entries)):
        before = {"byte": reader.byte, "bit": reader.bit}
        try:
            incremental = reader.bits(1) == 1
            index = (0 if previous is None else previous + 1) if incremental else reader.bits(14)
            value = reader.string()
        except ValueError as error:
            parse_error = {"entry": number, "error": str(error), "before": before,
                           "at": {"byte": reader.byte, "bit": reader.bit}}
            break
        slot_type = types[index] if index < len(types) else None
        entries.append({"index": index, "type": slot_type,
                        "accepted_as_text": slot_type is not None and (slot_type >= 23 or slot_type == 21),
                        "incremental": incremental, "value": value.decode("latin-1"),
                        "before": before, "after": {"byte": reader.byte, "bit": reader.bit}})
        previous = index
    return {"text_count": count, "inspected_prefix_count": len(entries),
            "remaining_unparsed": count - len(entries), "text_entries": entries, "parse_error": parse_error,
            "after_text": {"byte": reader.byte, "bit": reader.bit}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=Path("runs/gamestate-3426.bin"))
    parser.add_argument("--types", type=Path,
                        default=Path("evidence/experiments/20261023-client-slot-types-1649370.bin"))
    parser.add_argument("--output", type=Path, default=Path("runs/1649370-configstrings-inspect.json"))
    parser.add_argument("--max-entries", type=int, default=3,
                        help="stop after the verified prefix (default: 3)")
    args = parser.parse_args()
    if not 1 <= args.max_entries <= 3:
        parser.error("only the first three entries have been verified")
    report = inspect(args.payload.read_bytes(), args.types.read_bytes(), args.max_entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rejected = [row for row in report["text_entries"] if not row["accepted_as_text"]]
    print(json.dumps({"text_count": report["text_count"], "parsed_count": len(report["text_entries"]),
                      "parse_error": report["parse_error"], "rejected_count": len(rejected),
                      "first_rejected": rejected[:10], "after_text": report["after_text"],
                      "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
