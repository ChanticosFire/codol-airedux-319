"""Export packet-bounded `p` snapshot bodies from a demo.

    python tools/export_demo_frames.py <demo> --out runs/demo-frames-big --min 100 --top 5

The `p` command is nested inside a length-delimited outer type-2 packet.
The sampled demo's 725 `p` bodies all have delta_distance=1 and require a
matching predecessor. Use parse_demo_outer.py to export its full baseline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from parse_demo_outer import COMMAND_P, parse


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
    records, footer = parse(data)
    frames = []
    for row in records:
        if row["type"] != "packet":
            continue
        start, end = row["payload_offset"], row["end"]
        for match in COMMAND_P.finditer(data[start:end]):
            body_offset = start + match.end()
            blob = data[body_offset:end]
            if len(blob) >= args.min and blob[0] == 0:
                frames.append((blob, body_offset, end, row["sequence"],
                               int.from_bytes(match.group(1), "little"),
                               int(match.group(2))))
    if args.order == "size":
        frames.sort(key=lambda item: len(item[0]), reverse=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (blob, offset, end, outer_sequence, text_sequence, argument) in enumerate(frames[:args.top]):
        path = out / f"{i:02d}-{len(blob)}.bin"
        path.write_bytes(blob)
        rows.append({"file": path.name, "size": len(blob), "head": blob[:16].hex(),
                     "delta_distance": blob[5] if len(blob) > 5 else None,
                     "outer_sequence": outer_sequence, "text_sequence": text_sequence,
                     "body_offset": offset, "packet_end": end,
                     "command": f"p {argument}"})
    print(json.dumps({"frames": len(frames), "footer_offset": footer,
                      "exported": rows}, ensure_ascii=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
