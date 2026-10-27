"""Build a 1649370 snapshot that carries two player entities (experiment).

Field indices for entity type 1 come from `server1649370/entity_fields164.py`:
index 2 uses codec -83 (position axis 0 = x), index 1 uses -82 (axis 1 = y),
index 6 uses -81 (axis 2 = z), so a player entity's origin is
(field2, field1, field6).

    python tools/build_entity_frame_1649370.py --output runs/r703-entities.bin
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server1649370.wire164 import _word, build_snapshot

ENTITY_FIELD_X = 2
ENTITY_FIELD_Y = 1
ENTITY_FIELD_Z = 6
ENTITY_TYPE_PLAYER = 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--weapon-id", type=int, default=78)
    ap.add_argument("--clip-count", type=int, default=30)
    ap.add_argument("--health", type=int, default=100)
    ap.add_argument("--view-height-current", type=float, default=60.0)
    ap.add_argument("--origin", default="336,60,260.5")
    ap.add_argument("--second", default="400,60,260.5",
                    help="second player entity origin x,y,z")
    args = ap.parse_args()
    origin = tuple(float(part) for part in args.origin.split(","))
    second = tuple(float(part) for part in args.second.split(","))
    if len(origin) != 3 or len(second) != 3:
        ap.error("origins must be three numbers")

    values = {
        0x00: 72192, 0x04: 0, 0xA4: 800, 0xB0: 190, 0xC0: 1023,
        0x2C: 0, 0x158: 0, 0x16C: 60,
        0x170: _word(args.view_height_current), 0x174: 0x12345678,
        0x4C: args.weapon_id, 0x15C: 1023, 0x10: 0,
        0x30: _word(origin[0]), 0x34: _word(origin[1]), 0x38: _word(origin[2]),
        0x3F8: args.weapon_id, 0x3FC: args.weapon_id,
    }
    entities = [
        (0, ENTITY_TYPE_PLAYER, {ENTITY_FIELD_X: _word(origin[0]),
                                 ENTITY_FIELD_Y: _word(origin[1]),
                                 ENTITY_FIELD_Z: _word(origin[2])}),
        (1, ENTITY_TYPE_PLAYER, {ENTITY_FIELD_X: _word(second[0]),
                                 ENTITY_FIELD_Y: _word(second[1]),
                                 ENTITY_FIELD_Z: _word(second[2])}),
    ]
    frame = build_snapshot(values, server_time=72192,
                           tail_weapon=args.weapon_id,
                           tail_clip_count=args.clip_count,
                           tail_health=args.health,
                           entities=entities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(frame)
    print(json.dumps({"output": str(args.output), "bytes": len(frame),
                      "sha256": hashlib.sha256(frame).hexdigest(),
                      "entities": [[number, type_, {k: hex(v) for k, v in fields.items()}]
                                   for number, type_, fields in entities],
                      "origin": list(origin), "second": list(second)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
