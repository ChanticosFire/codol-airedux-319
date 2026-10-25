"""Insert or overwrite bits inside a snapshot's bit stream.

The playerState block starts at bit 67 in the compact snapshot.  Every field
begins with a single `changed` bit; when it is 0 the field carries no value.  To
make the client accept a `weapon` value we must turn that changed bit on and
append its encoding, which shifts every later bit.  This tool does the bit-level
surgery and keeps the trailing EOF byte intact.

    python tools/snapshot_bits_1649370.py --in runs/a.bin --out runs/b.bin \
        --at 460 --insert 1100000000
    python tools/snapshot_bits_1649370.py --in runs/a.bin --out runs/b.bin --dump 440 500
"""
from __future__ import annotations

import argparse
from pathlib import Path

EOF_BYTE = 0x05


def read_bits(blob: bytes) -> list[int]:
    return [(blob[i >> 3] >> (i & 7)) & 1 for i in range(len(blob) * 8)]


def write_bits(bits: list[int]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, v in enumerate(bits):
        if v:
            out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", type=Path, required=True)
    ap.add_argument("--out", dest="dst", type=Path, required=True)
    ap.add_argument("--at", type=int, help="bit position to modify")
    ap.add_argument("--insert", help="bit string to insert at --at")
    ap.add_argument("--set", help="bit string that overwrites bits starting at --at")
    ap.add_argument("--dump", nargs=2, type=int, metavar=("START", "END"))
    args = ap.parse_args()

    data = args.src.read_bytes()
    body, eof = data[:-1], data[-1]
    if eof != EOF_BYTE:
        raise SystemExit(f"unexpected EOF byte {eof:#x}")
    bits = read_bits(body)

    if args.dump:
        start, end = args.dump
        for s in range(start, end, 16):
            seg = "".join(str(bits[i]) for i in range(s, min(s + 16, end, len(bits))))
            print(f"bit {s:5d}: {seg}")
        return 0

    payload = [int(c) for c in (args.insert or args.set or "") if c in "01"]
    if args.at is None or not payload:
        raise SystemExit("need --at and --insert/--set")

    if args.insert:
        new_bits = bits[: args.at] + payload + bits[args.at:]
    else:
        new_bits = bits[: args.at] + payload + bits[args.at + len(payload):]

    new_body = write_bits(new_bits)
    args.dst.write_bytes(new_body + bytes([EOF_BYTE]))
    print(f"{args.dst}: {len(data)} -> {len(new_body) + 1} bytes, "
          f"bits {len(bits)} -> {len(new_bits)}, at {args.at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
