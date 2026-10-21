"""Reassemble 2697 gamestate fragments captured from the reference server.

Each file is a CODOL_WritePacket fragment:
  u32 sequence|FRAGMENT_BIT, u8 index, u8 count-1, u16 stride, u16 chunk, data
The payload is XOR-encoded with challenge ^ sequence (before the fragment
header), matching SV_Netchan_Encode; this tool accepts the challenge and
reassembles the plaintext message.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--cookie", type=int, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    files = sorted(path for path in args.directory.glob("*.bin")
                   if len(path.name) > 4 and path.name[:3].isdigit() and path.name[3] == "-")
    if not files:
        raise SystemExit("no fragment files")
    decoded = {}
    for path in files:
        raw = path.read_bytes()
        sequence = int.from_bytes(raw[:4], "little") & 0x7FFFFFFF
        key = (args.cookie ^ sequence) & 0xFF
        index = raw[4]
        count = raw[5] + 1
        stride = int.from_bytes(raw[6:8], "little")
        chunk = int.from_bytes(raw[8:10], "little")
        data = raw[10:10 + chunk]
        if index == 0:
            decoded[index] = data[:4] + bytes(byte ^ key for byte in data[4:])
        else:
            decoded[index] = bytes(byte ^ key for byte in data)
        print(path.name, "seq", sequence, "index", index, "count", count,
              "stride", stride, "chunk", chunk)
    message = b"".join(decoded[index] for index in sorted(decoded))
    out = args.out or args.directory / "gamestate.bin"
    out.write_bytes(message)
    print("reassembled", len(message), "bytes ->", out)
    print("head", message[:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
