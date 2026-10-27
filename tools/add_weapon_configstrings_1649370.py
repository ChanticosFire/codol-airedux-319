"""Add the per-weapon name configstrings to a captured 1649370 gamestate.

The captured demo gamestate carries only 292 configstrings and none of the
weapon names.  The 1649370 client keeps weapon names at `5960 + weaponIndex`
(the composite `**` definitions observed at 7096-7130 are `5960 + 1136..1170`,
which is what fixes this base).  This tool merges `5960+0 .. 5960+1135` into an
existing gamestate and re-encodes it byte-exactly with the same writer the
server already uses for native gamestates.

    python tools/add_weapon_configstrings_1649370.py --source runs/r672-composite-count.bin \
        --names runs/r690-weapon-names.json --output runs/r690-gamestate-weaponnames.bin
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server1649370.native_gamestate import (build_native_gamestate,
                                            parse_native_gamestate)

WEAPON_CONFIGSTRING_BASE = 5960


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--names", type=Path, required=True,
                    help="JSON object mapping weapon index (as string) to name")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--base", type=int, default=WEAPON_CONFIGSTRING_BASE)
    args = ap.parse_args()

    payload = args.source.read_bytes()
    parsed = parse_native_gamestate(payload)
    rows = dict(parsed["configstrings"])
    checksum_feed = struct.unpack("<I", payload[-6:-2])[0]
    print(json.dumps({"source_rows": len(rows), "mapname": parsed["mapname"].decode(),
                      "gametype": parsed["gametype"].decode(),
                      "registration_checksum": parsed["registration_checksum"],
                      "checksum_feed": hex(checksum_feed)}, indent=1))

    names = json.loads(args.names.read_text(encoding="utf-8"))
    added = 0
    for index, name in names.items():
        index = int(index)
        value = name.encode("ascii")
        slot = args.base + index
        if slot in rows:
            continue
        rows[slot] = value
        added += 1

    merged = [(index, value) for index, value in sorted(rows.items())]
    built = build_native_gamestate(parsed["registration_checksum"],
                                   checksum_feed=checksum_feed,
                                   configstrings=merged,
                                   mapname=parsed["mapname"],
                                   gametype=parsed["gametype"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(built)

    check = parse_native_gamestate(built)
    index_map = dict(check["configstrings"])
    report = {
        "output": str(args.output),
        "bytes": len(built),
        "sha256": hashlib.sha256(built).hexdigest(),
        "added": added,
        "rows_after": len(check["configstrings"]),
        "slot_5960": index_map.get(args.base, b"").decode("ascii", "replace"),
        "slot_6038": index_map.get(args.base + 78, b"").decode("ascii", "replace"),
        "slot_7096": index_map.get(args.base + 1136, b"").decode("ascii", "replace"),
        "mapname": check["mapname"].decode(),
        "gametype": check["gametype"].decode(),
    }
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
