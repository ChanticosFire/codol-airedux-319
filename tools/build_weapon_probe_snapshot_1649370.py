"""Build a single 1649370 snapshot with a chosen registered weapon ID.

The zero-weapon form must match the established r546 73-byte baseline exactly.
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
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, default=Path("runs/r546-markers.bin"))
    args = ap.parse_args()
    if not 0 <= args.weapon_id <= 2047:
        ap.error("weapon ID must fit the 11-bit wire range")
    if not 0 <= args.viewmodel_index <= 1023:
        ap.error("viewmodel index must fit the observed 10-bit range")
    if not 0 <= args.clip_count <= 511:
        ap.error("clip count must fit the 9-bit probe range")
    common = {
        0x00: 72192, 0x04: 0, 0xA4: 800, 0xB0: 190, 0xC0: 1023,
        0x2C: 0, 0x158: 0, 0x16C: 60, 0x170: _word(0.3125),
        0x174: 0x12345678, 0x4C: 0, 0x15C: 1023, 0x10: 0,
        0x30: _word(111.5), 0x34: _word(222.5), 0x38: _word(333.5),
    }
    entities = [(0, 1, {2: _word(200.0)})]
    zero = build_snapshot(common, server_time=72192, entities=entities)
    if zero != args.baseline.read_bytes():
        raise SystemExit("zero-weapon frame no longer matches the known baseline")
    values = common | {0x4C: args.weapon_id, 0x15C: args.viewmodel_index,
                       0x3F8: args.weapon_id,
                       0x3FC: args.weapon_id}
    frame = build_snapshot(values, server_time=72192,
                           tail_weapon=args.weapon_id,
                           tail_clip_count=args.clip_count, entities=entities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(frame)
    print(json.dumps({"weapon_id": args.weapon_id,
                      "viewmodel_index": args.viewmodel_index, "bytes": len(frame),
                      "clip_count": args.clip_count,
                      "sha256": hashlib.sha256(frame).hexdigest(),
                      "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
