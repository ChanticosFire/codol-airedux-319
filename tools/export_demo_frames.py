"""Export large snapshot bodies from a demo as binary templates.

    python tools/export_demo_frames.py <demo> --out runs/demo-frames-big --min 100 --top 5

Each selected `p <frame>` record's trailing blob starts with svc_snapshot
(0x00). The u32 after the record marker is a sequence number, not a length.
These are delta snapshots: the sampled demo's 725 candidate p bodies all have
delta_distance=1. They require a compatible predecessor and are not standalone
first snapshots. Record boundaries are still heuristic.
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
    ap.add_argument("--order", choices=("size", "file"), default="size",
                    help="largest candidates first, or first snapshots in demo order")
    args = ap.parse_args()
    data = Path(args.demo).read_bytes()
    pos = 0
    heads = []
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
        heads.append((pos, sequence, match.group(1).decode(), match.end(), match.group(0)))
        pos += 5 + match.end()
    frames = []
    for index, (offset, sequence, kind, text_len, command) in enumerate(heads):
        if kind != "p":
            continue
        end = heads[index + 1][0] if index + 1 < len(heads) else len(data)
        blob = data[offset + 5 + text_len:end]
        if len(blob) >= args.min and blob[0] == 0:
            frames.append((blob, offset, end, sequence, command))
    if args.order == "size":
        frames.sort(key=lambda item: len(item[0]), reverse=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (blob, offset, end, sequence, command) in enumerate(frames[:args.top]):
        path = out / f"{i:02d}-{len(blob)}.bin"
        path.write_bytes(blob)
        rows.append({"file": path.name, "size": len(blob), "head": blob[:16].hex(),
                     "delta_distance": blob[5] if len(blob) > 5 else None,
                     "sequence": sequence, "record_offset": offset,
                     "record_end": end, "command": command[:-1].decode("latin-1")})
    print(json.dumps({"frames": len(frames), "exported": rows}, ensure_ascii=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
