"""Build the first 1649370 baseline snapshot accepted by the client.

The 1649370 snapshot parser (0x471E90) runs these sections in order:

    long serverTime | byte delta | byte flags | 1 bit has_base
    0x671D80 pre-block | 0x471D80 | 0x471980 | 0x471010 | 0x471560
    0x4475F0 glass block | byte EOF (0x05)

The pre-block and the first two sub-blocks are byte-identical to the 2697
baseline captured in ``runs/ring-dump-43.jsonl`` (seq 33, XOR cookie low byte
15).  The actor block (0x471010) of that capture is not 1649370-compatible, so
it is replaced with its empty terminator: flag 0, explicit 11-bit index 2047.
Sub-block 4 and the glass block are emitted as one zero bit each, then EOF.

Verified on 2026-10-23: client parser ends with error=0, cursor=166, bit=1323,
executes 0x472810 (clc+0x3BE4=1), moves to connection state 10 and starts
sending usercmds.

Usage:
    python tools/build_1649370_snapshot.py --source runs/snapshot-2697-only.bin \
        --out runs/snapshot-hybrid-empty-actors.bin
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SOURCE_PREFIX = 164          # bytes kept from the 2697 body
ACTOR_BIT_START = 1309       # first bit of the 0x471010 actor block
KEPT_BITS_IN_PREFIX = 5      # low 5 bits of byte 163 belong to sub-block 2
ACTOR_EMPTY_INDEX = 0x7FF    # 11-bit terminator understood by 0x471010
EOF = 0x05


def build(source: bytes) -> bytes:
    if len(source) < SOURCE_PREFIX + 4:
        raise ValueError("2697 source body is too short")
    if source[0] != 0:
        raise ValueError("source must start with svc 0 (snapshot)")
    body = bytearray(source[:SOURCE_PREFIX])
    body[SOURCE_PREFIX - 1] &= (1 << KEPT_BITS_IN_PREFIX) - 1
    bit = ACTOR_BIT_START

    def write(value: int, width: int) -> None:
        nonlocal bit
        for shift in range(width):
            if bit & 7 == 0:
                body.append(0)
            body[bit >> 3] |= ((value >> shift) & 1) << (bit & 7)
            bit += 1

    write(0, 1)                    # actor flag: explicit index
    write(1, 1)                    # 11-bit form
    write(ACTOR_EMPTY_INDEX, 11)   # actor list terminator
    write(0, 1)                    # sub-block 4 (0x471560) empty
    write(0, 1)                    # glass block (0x4475F0) empty
    if bit >> 3 != len(body) - 1:
        raise ValueError("bit stream and byte cursor diverged")
    body.append(EOF)
    return bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="2697 baseline body starting with svc 0")
    parser.add_argument("--out", type=Path, default=Path("runs/snapshot-hybrid-empty-actors.bin"))
    args = parser.parse_args()
    payload = build(args.source.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    print(f"wrote {args.out} ({len(payload)} bytes) sha256={hashlib.sha256(payload).hexdigest()}")
    print(payload.hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
