"""Drive a real 2697 server through connect -> stats -> clc_move -> gamestate.

This is the offline (no game client) harness for the Build 1649370 bridge
work: it reproduces the text handshake the client uses, uploads a complete
32768-byte profile in the archive layout the server expects, then sends the
first clc_move and records whatever netchan fragments come back.

    python tools/probe_2697_stats_gamestate.py --port 28970
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import time
import zlib
from pathlib import Path


def encode_name(name: str) -> str:
    """Build 1649370's base64 name form (the 2697 archive decoder expects it)."""
    import base64

    return base64.b64encode(name.encode("utf-8")).decode("ascii")


def build_stats_packets() -> list[bytes]:
    profile = bytearray(32768)
    struct.pack_into("<I", profile, 4, 220)
    struct.pack_into("<I", profile, 8, 0xE4FD5218)
    struct.pack_into("<I", profile, 0, zlib.crc32(bytes(profile[4:])) & 0xFFFFFFFF)
    stream = zlib.compress(bytes(profile), 6)
    count = (len(stream) + 1237) // 1238
    return [b"\xff\xff\xff\xffstats\0" + bytes([i]) + struct.pack("<H", len(stream))
            + stream[i * 1238:(i + 1) * 1238] for i in range(count)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=28970)
    parser.add_argument("--name", default="AdministraClient")
    parser.add_argument("--xuid", default="0cf7ee44e08c4c28")
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--out", default="runs/2697-stats-gamestate-probe.json")
    parser.add_argument("--dump", default="runs/2697-stats-gamestate-packets.bin")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)
    target = (args.host, args.port)
    result: dict = {"target": f"{args.host}:{args.port}", "steps": [], "packets": []}
    captured = bytearray()

    def record(direction: str, data: bytes, source=None) -> None:
        result["packets"].append({
            "dir": direction, "length": len(data),
            "hex": data[:160].hex(),
            "ascii": data[:160].decode("latin-1", errors="replace"),
            "source": f"{source[0]}:{source[1]}" if source else None,
            "t": round(time.monotonic(), 3),
        })

    try:
        local = "a731af49a6a2c7e2"
        packet = b"\xff\xff\xff\xffgetchallenge 0 \"" + local.encode() + b"\""
        sock.sendto(packet, target)
        challenge, source = sock.recvfrom(4096)
        record("in", challenge, source)
        cookie = challenge.split(b"\x00")[0].decode("latin-1").split()[-1]
        result["steps"].append({"step": "getchallenge", "cookie": cookie})

        info = ("\\name\\%s\\xuid\\%s\\challenge\\%s\\natType\\1\\checksum\\0"
                "\\2490\\1649370\\statver\\1") % (encode_name(args.name), args.xuid, cookie)
        connect = ("\xff\xff\xff\xffconnect %s \"%s\"" % (args.xuid, info)).encode("latin-1")
        sock.sendto(connect, target)
        response, source = sock.recvfrom(8192)
        record("in", response, source)
        result["steps"].append({"step": "connect",
                                 "connect_response": response.decode("latin-1", "replace")})
        if b"connectResponse" not in response:
            raise RuntimeError("no connectResponse")

        # Stats upload: 25 archive-format blocks in one burst.
        stats = build_stats_packets()
        for item in stats:
            sock.sendto(item, target)
        result["steps"].append({"step": "stats_sent", "blocks": len(stats)})

        deadline = time.monotonic() + 4
        got_stat_response = False
        while time.monotonic() < deadline:
            try:
                data, source = sock.recvfrom(65535)
            except socket.timeout:
                break
            record("in", data, source)
            if b"statResponse" in data:
                got_stat_response = True
                result["steps"].append({"step": "statResponse",
                                         "ascii": data.decode("latin-1", "replace")})
                break
        result["stat_response"] = got_stat_response

        # First clc_move: sequence 1, clc_move (0x00), cmdCount 1, 200 zero bytes.
        move = struct.pack("<I", 1) + b"\x00" + bytes([1]) + bytes(200)
        sock.sendto(move, target)
        result["steps"].append({"step": "clc_move", "length": len(move)})

        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            try:
                data, source = sock.recvfrom(65535)
            except socket.timeout:
                continue
            record("in", data, source)
            captured.extend(struct.pack("<H", len(data)) + data)
    except Exception as error:  # noqa: BLE001 - report the failure
        result["error"] = repr(error)
    finally:
        sock.close()

    result["captured_bytes"] = len(captured)
    result["duration"] = round(args.seconds, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.dump).write_bytes(bytes(captured))
    print(json.dumps({key: result[key] for key in
                      ("target", "stat_response", "captured_bytes", "error") if key in result},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
