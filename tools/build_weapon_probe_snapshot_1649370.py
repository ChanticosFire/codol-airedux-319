"""Build a single 1649370 snapshot with a chosen registered weapon ID.

The zero-weapon form must match the established r546 73-byte baseline exactly
while the origin is the marker triple.  Any other origin is a positioning probe,
so the baseline comparison is skipped and reported as such.
Nonzero IDs are diagnostic probes; they are not evidence of a working loadout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server1649370.wire164 import _word, build_snapshot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weapon-id", type=int, required=True)
    ap.add_argument("--viewmodel-index", type=int, default=1023,
                    help="diagnostic playerState viewmodelIndex; 1023 is the known baseline")
    ap.add_argument("--clip-count", type=int, default=0,
                    help="diagnostic clip record; 0 preserves the known weapon probe")
    ap.add_argument("--origin", default="111.5,222.5,333.5",
                    help="playerState origin; the default is the marker triple")
    ap.add_argument("--view-height-current", type=float, default=0.3125,
                    help="ps+0x170 eye height; the historical marker value is 0.3125")
    ap.add_argument("--pm-type", type=int, default=0,
                    help="playerState pm_type byte; a real 2021 demo baseline carries 5")
    ap.add_argument("--health", type=int, default=0,
                    help="tail stats[0] (STAT_HEALTH); 0 may read as dead")
    ap.add_argument("--field", action="append", default=[],
                    help="extra playerState field as offset=value, repeatable")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, default=Path("runs/r546-markers.bin"))
    args = ap.parse_args()
    if not 0 <= args.weapon_id <= 2047:
        ap.error("weapon ID must fit the 11-bit wire range")
    if not 0 <= args.viewmodel_index <= 1023:
        ap.error("viewmodel index must fit the observed 10-bit range")
    if not 0 <= args.clip_count <= 511:
        ap.error("clip count must fit the 9-bit probe range")
    try:
        origin = tuple(float(part) for part in args.origin.split(","))
        if len(origin) != 3:
            raise ValueError
    except ValueError:
        ap.error("origin must be three comma separated numbers")
    default_origin = origin == (111.5, 222.5, 333.5)
    common = {
        0x00: 72192, 0x04: args.pm_type, 0xA4: 800, 0xB0: 190, 0xC0: 1023,
        0x2C: 0, 0x158: 0, 0x16C: 60, 0x170: _word(args.view_height_current),
        0x174: 0x12345678, 0x4C: 0, 0x15C: 1023, 0x10: 0,
        0x30: _word(origin[0]), 0x34: _word(origin[1]), 0x38: _word(origin[2]),
    }
    entities = [(0, 1, {2: _word(200.0)})]
    zero = build_snapshot(common, server_time=72192, entities=entities)
    baseline_ok = None
    if default_origin:
        baseline_ok = zero == args.baseline.read_bytes()
        if not baseline_ok:
            raise SystemExit("zero-weapon frame no longer matches the known baseline")
    values = common | {0x4C: args.weapon_id, 0x15C: args.viewmodel_index,
                       0x3F8: args.weapon_id,
                       0x3FC: args.weapon_id}
    for item in args.field:
        try:
            offset, value = item.split("=")
            values[int(offset, 0)] = int(value, 0)
        except ValueError:
            ap.error(f"--field expects offset=value, got {item!r}")
    frame = build_snapshot(values, server_time=72192,
                           tail_weapon=args.weapon_id,
                           tail_clip_count=args.clip_count, tail_health=args.health,
                           entities=entities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(frame)
    print(json.dumps({"weapon_id": args.weapon_id,
                      "viewmodel_index": args.viewmodel_index, "bytes": len(frame),
                      "clip_count": args.clip_count, "origin": list(origin),
                      "pm_type": args.pm_type, "health": args.health,
                      "baseline_checked": baseline_ok,
                      "sha256": hashlib.sha256(frame).hexdigest(),
                      "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
