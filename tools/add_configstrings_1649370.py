"""Merge arbitrary configstring entries into a captured 1649370 gamestate.

The real 2021 demos show the server setting two configstrings around match
start that our own gamestate never carries:

    d 435 1               (match start flag)
    d 15 1825900          (match time value)
    ... at end ...
    d 435 0 / d 15 0 / d 23 \\winner\\-2

This tool adds or replaces entries and re-encodes the gamestate with the same
writer the native gamestate builder uses.

    python tools/add_configstrings_1649370.py --source runs/r672-composite-count.bin \
        --entries "[[435,\"1\"],[15,\"1825900\"]]" --output runs/r694-gamestate.bin
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--entries", required=True,
                    help='JSON [[index,"value"],...] entries to add or replace')
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    payload = args.source.read_bytes()
    parsed = parse_native_gamestate(payload)
    rows = dict(parsed["configstrings"])
    checksum_feed = struct.unpack("<I", payload[-6:-2])[0]
    added = []
    replaced = []
    for index, value in json.loads(args.entries):
        index = int(index)
        encoded = str(value).encode("ascii")
        if index in rows:
            replaced.append([index, rows[index].decode("latin-1", "replace"),
                             encoded.decode("latin-1", "replace")])
        else:
            added.append(index)
        rows[index] = encoded

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
        "rows_before": len(parsed["configstrings"]),
        "rows_after": len(check["configstrings"]),
        "added": added,
        "replaced": replaced,
        "mapname": check["mapname"].decode(),
        "gametype": check["gametype"].decode(),
        "values": {str(index): index_map.get(index, b"").decode("latin-1", "replace")
                   for index, _ in json.loads(args.entries)},
    }
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
