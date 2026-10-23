"""Verify the snapshot encoder against bodies the client actually accepted.

`runs/snapshot-single22.bin` is the only playerState-carrying body this project
produced that the client accepted reproducibly (network state 10), and its ps
block measures 29 bits - exactly what the cost model predicts. This script
decodes that block with the same codec module used to write it, so a change that
breaks the encoder cannot silently pass.

Usage:
    python tools/verify_encoder.py
Exit code 0 means every assertion held.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server1649370.ps_codec import (  # noqa: E402
    BitReader,
    read_distance,
    read_field,
)

PS_START = 1308          # measured ps entry bit in the hybrid prefix
EXPECTED_BITS = 29       # measured, and predicted by the cost model
BODY = ROOT / "runs" / "snapshot-single22.bin"


def bits_of(path: Path) -> BitReader:
    return BitReader(path.read_bytes())


def main() -> int:
    if not BODY.exists():
        print(f"MISSING: {BODY}")
        return 2

    reader = bits_of(BODY)
    # skip the hybrid prefix: PS_START is a BIT offset, not a byte count
    for _ in range(PS_START // 8):
        reader.byte()
    if PS_START % 8:
        reader.bits(PS_START % 8)

    failures = 0

    def check(name: str, got, want) -> None:
        nonlocal failures
        if got != want:
            failures += 1
            print(f"FAIL {name}: got {got!r} want {want!r}")

    start = reader.position
    has_ps = reader.bit()
    check("has-ps", has_ps, 1)
    mode = reader.bit()
    check("mode", mode, 0)
    last = reader.bits(5)
    check("last", last, 0)
    present = reader.bit()
    check("present", present, 0)
    continuation = reader.bit()
    check("continuation", continuation, 1)
    target = reader.bits(5)
    check("V (target position)", target, 22)
    distance = read_distance(reader)
    check("distance", distance, 23)
    value = read_field(reader, 11)
    check("landing field (codec 11)", value, 0)
    exit_bit = reader.bit()
    check("exit (has-ps)", exit_bit, 0)

    consumed = reader.position - start
    check("ps length", consumed, EXPECTED_BITS)

    print(f"ps block at bit {start}, consumed {consumed} bits "
          f"(expected {EXPECTED_BITS})")
    print(f"verify_encoder failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
