"""Split a demo into records by locating every `01 <u32 seq> <text-command>` header.

    python tools/split_demo_records.py <demo> --output split.json --limit 8

The u32 is a record sequence number, not a length. Record boundaries come from
the next text header. Everything between the NUL and that header is the binary
payload carried with the command; for `p <n>` it begins with a snapshot body.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import struct
from pathlib import Path

HEAD = re.compile(rb"([dpsrvw]) (\d+|none)((?: [^\x00]*)?)\x00")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("demo")
    ap.add_argument("--output")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    data = Path(args.demo).read_bytes()
    headers: list[tuple[int, int, str, int, bytes]] = []
    pos = 0
    while pos + 5 <= len(data):
        if data[pos] != 0x01:
            pos += 1
            continue
        sequence = struct.unpack_from("<I", data, pos + 1)[0]
        if not (0 <= sequence <= 0x20000):
            pos += 1
            continue
        match = HEAD.match(data[pos + 5:pos + 5 + 64])
        if not match:
            pos += 1
            continue
        headers.append((pos, sequence, match.group(1).decode(), match.end(), data[pos + 5:pos + 5 + match.end()]))
        pos += 5 + match.end()
    blobs: list[dict] = []
    sizes: dict[str, list[int]] = collections.defaultdict(list)
    for index, (offset, sequence, kind, text_len, text) in enumerate(headers):
        end = headers[index + 1][0] if index + 1 < len(headers) else len(data)
        blob = data[offset + 5 + text_len:end]
        sizes[kind].append(len(blob))
        if len(blobs) < args.limit and kind == "p":
            blobs.append({"offset": offset, "sequence": sequence, "kind": kind,
                          "text": text.decode("latin-1", "replace"),
                          "blob_len": len(blob), "blob": blob[:48].hex()})
    summary = {k: {"count": len(v), "avg": round(sum(v) / len(v), 1) if v else 0,
                   "max": max(v) if v else 0} for k, v in sizes.items()}
    result = {"demo": str(args.demo), "records": len(headers),
              "kinds": summary, "samples": blobs}
    text = json.dumps(result, ensure_ascii=True, indent=1)
    print(text[:5000])
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
