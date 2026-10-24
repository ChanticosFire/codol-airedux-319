"""Parse the weapon tables at the tail of a snapshot/gamestate configstring block.

    python tools/parse_gamestate_tables.py runs/demo-outer-exact/gamestate-stream-6407.bin

Layout after ``svc_configstrings`` (0x04) + u16 count:

    per configstring: 1 bit continue-flag  [14 bit index when flag==0]  NUL string
    then:            10 bit alias count
                     11 bit recipe count
    then:            0x05 close

Bit order is most-significant-bit first, matching the engine's msg reader.
"""
from __future__ import annotations

import struct
import sys


class Bits:
    def __init__(self, data: bytes, offset: int) -> None:
        self.data = data
        self.bit = offset * 8

    def read(self, count: int) -> int:
        value = 0
        for _ in range(count):
            byte = self.data[self.bit >> 3]
            value = (value << 1) | ((byte >> (7 - (self.bit & 7))) & 1)
            self.bit += 1
        return value

    def byte_offset(self) -> int:
        return self.bit >> 3


def cstring(data: bytes, offset: int) -> tuple[str, int]:
    end = data.find(b"\0", offset)
    if end < 0:
        return "", len(data)
    return data[offset:end].decode("latin-1", "replace"), end + 1


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "runs/demo-outer-exact/gamestate-stream-6407.bin"
    data = open(path, "rb").read()
    print("size", len(data), "head", data[:8].hex(" "))

    # locate svc 0x04 (configstrings) after the gamestate preamble
    start = data.find(b"\x04", 20)
    if start < 0:
        print("no configstring block")
        return 1
    count = struct.unpack_from("<H", data, start + 1)[0]
    print("svc@", hex(start), "configstring count", count)

    bits = Bits(data, start + 3)
    entries = []
    index = -1
    bad = 0
    for _ in range(count):
        flag = bits.read(1)
        if flag:
            index += 1
        else:
            index = bits.read(14)
        offset = bits.byte_offset()
        text, nxt = cstring(data, offset)
        bits.bit = nxt * 8
        entries.append((index, text))
        if nxt >= len(data):
            bad += 1
            break
    print("parsed", len(entries), "entries, last index", index, "end byte", bits.byte_offset())
    print("sample", [(i, ascii(t[:30])) for i, t in entries[:3]])
    print("tail", [(i, ascii(t[:30])) for i, t in entries[-3:]])

    alias = bits.read(10)
    recipe = bits.read(11)
    print("alias count =", alias, " recipe count =", recipe,
          " at byte", bits.byte_offset(), " next byte", data[bits.byte_offset():bits.byte_offset()+8].hex(" "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
