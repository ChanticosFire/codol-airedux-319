"""Export large snapshot bodies from a demo as binary templates.

    python tools/export_demo_frames.py <demo> --out runs/demo-frames-big --min 100 --top 5

Each `p <frame>` record's trailing blob starts with svc_snapshot (0x00) and the
header fields verified in docs/SNAPSHOT-FORMAT-VERIFIED.md, so these blobs are
exact snapshot bodies the real server sent - ready to be replayed as templates.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

HEAD = re.compile(rb"([dpsrvw]) (\d+|none)((?: [^\x00]*)?)\x00")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("demo")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min", type=int, default=100)
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()
    data = Path(args.demo).read_bytes()
    pos = 0
    heads = []
    while pos + 5 <= len(data):
        if data[pos] != 0x01:
            pos += 1
            continue
        length = struct.unpack_from("<I", data, pos + 1)[0]
        if not (0 <= length <= 0x20000):
            pos += 1
            continue
        match = HEAD.match(data[pos + 5:pos + 5 + 64])
        if not match:
            pos += 1
            continue
        heads.append((pos, match.group(1).decode(), match.end()))
        pos += 5 + match.end()
    frames = []
    for index, (offset, kind, text_len) in enumerate(heads):
        if kind != "p":
            continue
        end = heads[index + 1][0] if index + 1 < len(heads) else len(data)
        blob = data[offset + 5 + text_len:end]
        if len(blob) >= args.min:
            frames.append(blob)
    frames.sort(key=len, reverse=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, blob in enumerate(frames[:args.top]):
        path = out / f"{i:02d}-{len(blob)}.bin"
        path.write_bytes(blob)
        rows.append({"file": path.name, "size": len(blob), "head": blob[:16].hex()})
    print(json.dumps({"frames": len(frames), "exported": rows}, ensure_ascii=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
