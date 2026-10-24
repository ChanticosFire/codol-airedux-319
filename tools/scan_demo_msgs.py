"""Scan a .demo file for candidate message headers and their text payloads.

    python tools/scan_demo_msgs.py <demo> [--limit 40]

A message candidate is `01 <u32 len> <payload>` where 5 <= len <= 0x20000 and
the payload starts with a printable command prefix (d/p/s/r/v/w).  This avoids
having to know the exact header end: the scan reports every plausible record so
the real message stream can be reconstructed.
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

CMD = re.compile(rb"^[dpsrvwc] [0-9a-zA-Z_\"(.+-]")


def scan(data: bytes, limit: int = 40) -> dict:
    hits: list[dict] = []
    for i in range(len(data) - 6):
        if data[i] != 0x01:
            continue
        length = struct.unpack_from("<I", data, i + 1)[0]
        if not (5 <= length <= 0x20000):
            continue
        if i + 5 + length > len(data):
            continue
        payload = data[i + 5:i + 5 + length]
        if not CMD.match(payload):
            continue
        hits.append({"offset": i, "len": length,
                     "text": payload[:80].decode("latin-1", "replace")})
        if len(hits) >= limit:
            break
    return {"size": len(data), "candidates": len(hits), "items": hits}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                r"E:\GAME\COD\使命召唤OL\main\demo\0C-2021-8-26[19-26-24]war.demo")
    limit = 40
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    result = scan(path.read_bytes(), limit)
    print(json.dumps(result, ensure_ascii=True, indent=1)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
