"""Decode the server-to-client stream captured by ring_bridge --dump-in.

Fragment layout (netchan.c Netchan_TransmitNextFragment, server side):
    u32 sequence|FRAGMENT_BIT, u32 fragmentStart, u16 fragmentLength, data...

The reassembled message is u32 outgoingSequence + encoded body.  The body was
encrypted by CODOL_Xor with key = (uint8_t)(challenge ^ outgoingSequence) and
the client's lastClientCommandString (empty string means the constant key).

    python tools/decode_ring_dump.py runs/ring-dump-43.jsonl --challenge -767244017
"""
from __future__ import annotations

import argparse
import collections
import json
import struct
from pathlib import Path


def reassemble(rows: list[dict]) -> dict[int, bytes]:
    """COOL_WritePacket fragment: u32 seq|FRAG, u8 index, u8 last, u16 stride, u16 chunk, data."""
    groups: dict[int, dict[int, bytes]] = collections.defaultdict(dict)
    whole: dict[int, bytes] = {}
    for row in rows:
        data = bytes.fromhex(row["hex"])
        if len(data) < 6 or data.startswith(b"\xff\xff\xff\xff"):
            continue
        header = struct.unpack_from("<I", data, 0)[0]
        if not (header & 0x80000000):
            whole[header] = data[4:]
            continue
        sequence = header & 0x7FFFFFFF
        index, last = data[4], data[5]
        stride, chunk = struct.unpack_from("<HH", data, 6)
        groups[sequence][index] = data[10:10 + chunk]
    messages = dict(whole)
    for sequence, parts in groups.items():
        out = bytearray()
        for index in sorted(parts):
            out += parts[index]
        if out:
            messages[sequence] = bytes(out)
    return messages


def decode(body: bytes, challenge: int, sequence: int, command: bytes = b"") -> bytes:
    key = (challenge ^ sequence) & 0xFF
    data = bytearray(body)
    index = 0
    for i in range(len(data)):
        if command:
            if index >= len(command) or command[index] == 0:
                index = 0
            key ^= (command[index] << (i & 1)) & 0xFF
            index += 1
        data[i] ^= key & 0xFF
    return bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path)
    parser.add_argument("--challenge", type=int, required=True)
    parser.add_argument("--command", default="")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.dump.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    messages = reassemble(rows)
    print(f"packets={len(rows)} messages={len(messages)}")
    command = args.command.encode("latin-1")
    shown = 0
    for sequence in sorted(messages)[: args.limit]:
        raw = messages[sequence]
        plain = decode(raw[4:], args.challenge, sequence, command) if len(raw) >= 4 else b""
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in plain[:48])
        print(f"seq={sequence:<5} raw={len(raw):<6} head={plain[:24].hex():<48} {text}")
        shown += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
