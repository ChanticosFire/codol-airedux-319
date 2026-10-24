"""Extract the binary payload that follows each `p <frame>` command in a demo.

    python tools/extract_demo_frames.py <demo> --output frames.json --limit 5

Verified layout of one record:

    [0x01][u32 len][text ...][0x00][binary ...]        (len = text+NUL+binary)

For `p <n>` records the trailing binary is the packet-entity blob of that frame -
exactly what the real server sent in its snapshots, so these blobs are the
templates the gameserver should reproduce.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

HEAD_RE = re.compile(rb"([dpsrvw]) (\d+|none)((?: [^\x00]*)?)\x00")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("demo")
    ap.add_argument("--output")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()
    data = Path(args.demo).read_bytes()
    frames: list[dict] = []
    records = 0
    pos = 0
    while pos + 5 <= len(data):
        if data[pos] != 0x01:
            pos += 1
            continue
        length = struct.unpack_from("<I", data, pos + 1)[0]
        if not (5 <= length <= 0x20000) or pos + 5 + length > len(data):
            pos += 1
            continue
        payload = data[pos + 5:pos + 5 + length]
        match = HEAD_RE.match(payload)
        if not match:
            pos += 1
            continue
        records += 1
        kind = match.group(1).decode()
        text_end = match.end()
        blob = payload[text_end:]
        if kind == "p" and len(frames) < args.limit:
            frames.append({"offset": pos, "frame": match.group(2).decode(),
                           "record_len": length, "text_len": text_end,
                           "blob_len": len(blob), "blob": blob[:64].hex(),
                           "blob_head_ascii": blob[:32].decode("latin-1", "replace")})
        pos += 5 + length
    result = {"demo": str(args.demo), "records": records, "frames": len(frames),
              "items": frames}
    text = json.dumps(result, ensure_ascii=True, indent=1)
    print(text[:5000])
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
