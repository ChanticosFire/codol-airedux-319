"""Build a 1649370 configstring table from the captured 2697 gamestate.

The 2697 gamestate holds 174 printable NUL-separated strings (serverinfo, map
name, precache lists, compass-map entry, HUD status names, skeleton tags...).
The 1649370 client accepts any slot whose type byte is 0xFF, so the strings can
be re-emitted from slot 3 onward while slots 0/1/2 keep their verified values.

Usage:
    python tools/build_1649370_configstrings.py --out runs/configstrings-2697.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE = [
    (0, "\\g_gametype\\war\\mapname\\mp_cross_fire"),
    (1, ""),
    (2, "cod"),
]
SKIP = {"mp_cross_fire", "cod"}
MIN_LEN = 3
MAX_LEN = 900


def extract(payload: bytes) -> list[str]:
    runs = re.findall(rb"[ -~]{%d,}" % MIN_LEN, payload)
    seen = set()
    out = []
    for raw in runs:
        text = raw.decode("latin-1")
        text = text.replace("\t", " ").strip()
        if not text or len(text) > MAX_LEN:
            continue
        if text in SKIP or text in seen:
            continue
        if text.startswith("\\g_gametype"):
            continue
        seen.add(text)
        out.append(text)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gamestate", type=Path, default=Path("runs/gamestate-3426.bin"))
    parser.add_argument("--out", type=Path, default=Path("runs/configstrings-2697.json"))
    parser.add_argument("--types", type=Path,
                        default=Path("evidence/experiments/20261023-client-slot-types-1649370.bin"),
                        help="1649370 slot type table (12761 bytes)")
    parser.add_argument("--start-index", type=int, default=24,
                        help="first slot that may receive a captured string")
    parser.add_argument("--limit", type=int, default=400)
    args = parser.parse_args()
    strings = extract(args.gamestate.read_bytes())[: max(args.limit - 3, 0)]
    rows = [[index, value] for index, value in BASE]
    if args.types.is_file():
        types = args.types.read_bytes()
        slots = [index for index in range(max(args.start_index, 3), len(types))
                 if types[index] >= 0x17 or types[index] == 0x15]
    else:
        slots = list(range(args.start_index, args.start_index + len(strings)))
    for slot, value in zip(slots, strings):
        rows.append([slot, value])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows)} entries "
          f"({min(len(strings), len(slots))} from the capture, {len(slots)} text slots available)")
    for index, value in rows[:8]:
        print(f"  {index}: {value[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
