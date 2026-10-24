"""Parse the top-level CODOL 1649370 demo records without scanning text.

    python tools/parse_demo_outer.py <demo> --out runs/demo-outer

The sampled 2021-08 demo starts its record stream at 0x8020. Type 2 is
`02 <u32 sequence> <u32 length> <length bytes>`; type 1 is
`01 <u32 sequence> <52 bytes>`. Type 0 begins the footer. Text commands are
inside type-2 payloads, so the next text header is not a packet boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

START = 0x8020
PACKET = 2
AUX = 1
AUX_SIZE = 57
COMMAND_P = re.compile(rb"\x01(.{4})p (\d+)\x00", re.DOTALL)


def parse(data: bytes) -> tuple[list[dict], int]:
    records: list[dict] = []
    offset = START
    while offset + 5 <= len(data):
        kind = data[offset]
        sequence = struct.unpack_from("<I", data, offset + 1)[0]
        if kind == AUX:
            end = offset + AUX_SIZE
            if end > len(data):
                raise ValueError(f"truncated auxiliary record at {offset:#x}")
            records.append({"type": "aux", "offset": offset, "sequence": sequence,
                            "payload_offset": offset + 5, "payload_length": 52, "end": end})
        elif kind == PACKET:
            if offset + 9 > len(data):
                raise ValueError(f"truncated packet header at {offset:#x}")
            length = struct.unpack_from("<I", data, offset + 5)[0]
            end = offset + 9 + length
            if length > 0x20000 or end > len(data):
                raise ValueError(f"invalid packet length {length} at {offset:#x}")
            records.append({"type": "packet", "offset": offset,
                            "sequence": sequence, "payload_offset": offset + 9,
                            "payload_length": length, "end": end})
        else:
            break
        offset = end
    return records, offset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("demo", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--registration-checksum", type=lambda value: int(value, 0),
                        help="also export a natural-network gamestate with this map's live checksum")
    parser.add_argument("--checksum-feed", type=lambda value: int(value, 0),
                        help="replace the demo's zero checksum feed in the network export")
    args = parser.parse_args()
    data = args.demo.read_bytes()
    records, footer = parse(data)
    packets = [row for row in records if row["type"] == "packet"]
    aux = len(records) - len(packets)
    first_packet = data[packets[0]["payload_offset"]:packets[0]["end"]]
    gamestate_stream = (zlib.decompress(first_packet[4:])
                        if first_packet[:4] == b"\x00\x00\x00\x80" else None)
    baseline = []
    p_snapshots = []
    for row in packets:
        start, end = row["payload_offset"], row["end"]
        payload = data[start:end]
        # Four-byte message acknowledgement precedes the svc byte.
        if len(payload) >= 11 and payload[4] == 0 and payload[9] == 0:
            baseline.append((row, start + 4, payload[4:]))
        for match in COMMAND_P.finditer(payload):
            body_offset = start + match.end()
            body = data[body_offset:end]
            if len(body) >= 7 and body[0] == 0:
                p_snapshots.append((row, body_offset, body,
                                    int.from_bytes(match.group(1), "little"),
                                    int(match.group(2))))
    exports = []
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        if gamestate_stream:
            name = f"gamestate-stream-{len(gamestate_stream)}.bin"
            (args.out / name).write_bytes(gamestate_stream)
            wire_name = f"gamestate-payload-{len(gamestate_stream) + 4}.bin"
            (args.out / wire_name).write_bytes(b"\x00\x00\x00\x00" + gamestate_stream)
            exports.append({"file": name, "type": "gamestate-stream",
                            "outer_sequence": packets[0]["sequence"],
                            "body_offset": packets[0]["payload_offset"],
                            "body_length": len(gamestate_stream),
                            "wire_payload": wire_name,
                            "sha256": hashlib.sha256(gamestate_stream).hexdigest()})
            if args.registration_checksum is not None:
                if not 0 <= args.registration_checksum <= 0xffffffff:
                    raise ValueError("registration checksum must be uint32")
                wire = bytearray(b"\x00\x00\x00\x00" + gamestate_stream)
                cursor = 9
                for _ in range(2):  # mapname, then gametype
                    cursor = wire.index(0, cursor) + 1
                original = struct.unpack_from("<I", wire, cursor)[0]
                struct.pack_into("<I", wire, cursor, args.registration_checksum)
                feed_before = None
                if args.checksum_feed is not None:
                    if not 0 <= args.checksum_feed <= 0xffffffff or wire[-1] != 5:
                        raise ValueError("invalid checksum feed or gamestate trailer")
                    feed_before = struct.unpack_from("<I", wire, len(wire) - 5)[0]
                    struct.pack_into("<I", wire, len(wire) - 5, args.checksum_feed)
                patched_name = f"gamestate-network-{args.registration_checksum:08x}-{len(wire)}.bin"
                (args.out / patched_name).write_bytes(wire)
                exports.append({"file": patched_name, "type": "gamestate-network",
                                "checksum_offset": cursor,
                                "checksum_before": f"{original:#010x}",
                                "checksum_after": f"{args.registration_checksum:#010x}",
                                "feed_before": f"{feed_before:#010x}" if feed_before is not None else None,
                                "feed_after": f"{args.checksum_feed:#010x}" if args.checksum_feed is not None else None,
                                "sha256": hashlib.sha256(wire).hexdigest()})
        choices = [("baseline", row, position, blob, None, None)
                   for row, position, blob in baseline[:1]]
        choices += [("p-delta", row, position, blob, text_seq, arg)
                    for row, position, blob, text_seq, arg in p_snapshots[:args.limit]]
        for kind, row, position, blob, text_seq, arg in choices:
            name = f"{kind}-outer{row['sequence']}-{len(blob)}.bin"
            (args.out / name).write_bytes(blob)
            exports.append({"file": name, "type": kind, "outer_sequence": row["sequence"],
                            "body_offset": position, "body_length": len(blob),
                            "delta_distance": blob[5], "text_sequence": text_seq,
                            "p_argument": arg, "sha256": hashlib.sha256(blob).hexdigest()})
    print(json.dumps({"demo": str(args.demo), "size": len(data),
                      "records": len(records), "packets": len(packets), "auxiliary": aux,
                      "footer_offset": footer, "footer_head": data[footer:footer + 16].hex(),
                      "gamestate_decompressed_bytes": len(gamestate_stream) if gamestate_stream else None,
                      "baseline_candidates": len(baseline),
                      "p_snapshot_candidates": len(p_snapshots), "exports": exports},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
