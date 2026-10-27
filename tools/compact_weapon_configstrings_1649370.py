"""Move captured composite weapon configstrings after the loaded base roster.

This builds a test gamestate for the current offline client. It does not alter
the source file or claim that the resulting weapon definitions can be equipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_gamestate_1649370 import decode, encode

WEAPON_START = 5960
WEAPON_END = WEAPON_START + 1700


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--base-count", type=int, default=1135,
                    help="observed number of base weapon definitions before composites")
    ap.add_argument("--update-count", action="store_true",
                    help="also change configstring 12246 to the new one-past-last weapon ID")
    args = ap.parse_args()
    if args.input.resolve() == args.output.resolve():
        ap.error("input and output must be different files")
    if not 1 <= args.base_count < 1700:
        ap.error("base-count outside the weapon configstring range")

    source = args.input.read_bytes()
    gs = decode(source)
    if encode(gs) != source:
        raise SystemExit("source does not round-trip byte-exact")
    composites = [(index, value) for index, value in gs.texts
                  if WEAPON_START <= index < WEAPON_END]
    if not composites or not all(value.startswith(b"** ") for _, value in composites):
        raise SystemExit("weapon range contains unexpected non-composite text")
    old_indices = [index for index, _ in composites]
    if old_indices != list(range(old_indices[0], old_indices[0] + len(composites))):
        raise SystemExit("source composite indices are not contiguous")
    new_start = WEAPON_START + args.base_count + 1
    new_indices = list(range(new_start, new_start + len(composites)))
    if new_indices[-1] >= WEAPON_END:
        raise SystemExit("compacted composites exceed weapon range")

    mapping = dict(zip(old_indices, new_indices))
    if args.update_count:
        count_values = [value for index, value in gs.texts if index == 12246]
        expected_old_count = old_indices[-1] - WEAPON_START + 1
        if count_values != [str(expected_old_count).encode("ascii")]:
            raise SystemExit("source weapon count does not match old composite range")
        mapping[12246] = 12246
    new_count = new_indices[-1] - WEAPON_START + 1
    gs.texts = sorted(((mapping.get(index, index),
                        str(new_count).encode("ascii") if args.update_count and index == 12246 else value)
                       for index, value in gs.texts),
                      key=lambda item: item[0])
    output = encode(gs)
    if decode(output).texts != gs.texts:
        raise SystemExit("output verification failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(json.dumps({"input_sha256": hashlib.sha256(source).hexdigest(),
                      "output_sha256": hashlib.sha256(output).hexdigest(),
                      "count": len(composites), "old_range": [old_indices[0], old_indices[-1]],
                      "new_range": [new_indices[0], new_indices[-1]],
                      "new_weapon_count": new_count if args.update_count else None,
                      "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
