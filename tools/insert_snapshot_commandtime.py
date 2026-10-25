"""Insert a changed `commandTime` into the live snapshot's playerState block.

The ps block starts at bit 1430 in the compact 182-byte snapshot (measured via
the 0x471980 hook reading msg+0x20).  Its first field is playerState.commandTime
(descriptor index 0, type -97), encoded as

    [1 bit changed][1 bit mode][8-bit delta | 32-bit absolute]

For the compact snapshot the changed bit is 0, so the decoder never writes the
field and the client keeps uninitialised stack garbage.  This tool rewrites the
bit stream to changed=1, mode=1, and appends a 32-bit absolute value, shifting
the rest of the stream by 33 bits.  The server rereads the file for every send,
so a running session picks this up without a restart.

    python tools/insert_snapshot_commandtime.py --in runs/snap-live.bin --out runs/snap-live.bin --value 471192
"""
from __future__ import annotations

import argparse
from pathlib import Path

PS_BLOCK_BIT = 1430
EOF_BYTE = 0x05


def read_bits(blob: bytes, count: int) -> list[int]:
    return [(blob[i >> 3] >> (i & 7)) & 1 for i in range(count)]


def write_bits(bits: list[int]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, value in enumerate(bits):
        if value:
            out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", type=Path, required=True)
    parser.add_argument("--out", dest="dst", type=Path, required=True)
    parser.add_argument("--value", type=int, required=True)
    parser.add_argument("--bit", type=int, default=PS_BLOCK_BIT)
    args = parser.parse_args()

    data = args.src.read_bytes()
    body, eof = data[:-1], data[-1]
    if eof != EOF_BYTE:
        raise SystemExit(f"unexpected EOF byte {eof:#x} at end of snapshot")
    bits = read_bits(body, len(body) * 8)
    if bits[args.bit] != 0:
        raise SystemExit("commandTime changed bit is already 1; refusing to double-insert")
    value_bits = [(args.value >> i) & 1 for i in range(32)]
    new_bits = bits[: args.bit] + [1, 1] + value_bits + bits[args.bit + 1:]
    new_body = write_bits(new_bits)
    # keep only the significant bits: pad to a byte boundary, then re-append EOF
    args.dst.write_bytes(new_body + bytes([EOF_BYTE]))
    print(f"{args.dst}: {len(data)} -> {len(new_body) + 1} bytes, "
          f"inserted 33 bits at bit {args.bit}, commandTime={args.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
