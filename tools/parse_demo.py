"""Parse a CODOL .demo file into its message stream (offline, no client needed).

    python tools/parse_demo.py "E:\\GAME\\COD\\使命召唤OL\\main\\demo\\0C-2021-8-26[19-26-24]war.demo"

Message layout (verified against the `d 3635 ...` configstring at 0x11FB7):
    [u8 type][u32 little-endian length][length bytes of payload]
The header is 0x55 bytes; parsing starts right after it and walks the whole
file, so every gamestate/configstring/packetentity record becomes visible
without running the client.
"""
from __future__ import annotations

import collections
import json
import struct
import sys
from pathlib import Path

HEADER = 0x55


def parse(path: Path) -> dict:
    data = path.read_bytes()
    pos = HEADER
    rows: list[dict] = []
    while pos + 5 <= len(data):
        kind = data[pos]
        length = struct.unpack_from("<I", data, pos + 1)[0]
        if length < 0 or pos + 5 + length > len(data):
            rows.append({"offset": pos, "type": kind, "length": length, "truncated": True})
            break
        payload = data[pos + 5:pos + 5 + length]
        rows.append({"offset": pos, "type": kind, "length": length,
                     "head": payload[:48].hex(),
                     "text": payload[:80].decode("latin-1", "replace") if kind in (1, 2, 3) else ""})
        pos += 5 + length
    return {"size": len(data), "header": HEADER, "parsed": len(rows),
            "end": pos, "types": dict(collections.Counter(r["type"] for r in rows)),
            "first": rows[:12], "last": rows[-4:]}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                r"E:\GAME\COD\使命召唤OL\main\demo\0C-2021-8-26[19-26-24]war.demo")
    result = parse(path)
    print(json.dumps(result, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
