"""Extract all textual commands from a .demo file (offline, no client needed).

    python tools/extract_demo_cmds.py <demo> [--output out.json]

Commands look like `d 2557 "mp_crash_tropical" 1000` and are NUL-terminated.
The demo format is `01 <u32 len> <payload>` where len covers the command plus
trailing bytes, so this extractor keys on the text itself and reports counts and
a sample of every command kind (d/p/s/r/v/w/...) for template building.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

CMD_RE = re.compile(rb"([dpsrvwfc]) (\d+|none)((?: [^\x00]*)?)\x00")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("demo")
    ap.add_argument("--output")
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()
    data = Path(args.demo).read_bytes()
    kinds = collections.Counter()
    samples: dict[str, list[str]] = collections.defaultdict(list)
    total = 0
    for match in CMD_RE.finditer(data):
        total += 1
        kind = match.group(1).decode()
        kinds[kind] += 1
        if len(samples[kind]) < args.limit:
            samples[kind].append(match.group(0)[:-1].decode("latin-1", "replace"))
    result = {"demo": str(args.demo), "size": len(data), "total": total,
              "kinds": dict(kinds), "samples": {k: v for k, v in samples.items()}}
    text = json.dumps(result, ensure_ascii=True, indent=1)
    print(text[:6000])
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
