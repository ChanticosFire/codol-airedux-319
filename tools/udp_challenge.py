"""Minimal COD challenge responder for the 1649370 local match attempt.

The client's connect path sends `getchallenge` and expects a
`challengeResponse <number>` line back.  This responder answers from
127.0.0.1:<port> so a locally switched game state can finish the handshake
instead of showing the "无法连接主机" dialog.

    python tools/udp_challenge.py --port 8466 --seconds 120
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

CHALLENGE = -486178985


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8466)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--output")
    args = parser.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.settimeout(0.5)
    rows = []
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        try:
            data, peer = sock.recvfrom(4096)
        except socket.timeout:
            continue
        text = data.split(b"\x00")[0][:64]
        reply = None
        lowered = text.lower()
        if b"getchallenge" in lowered:
            reply = f"challengeResponse {CHALLENGE}".encode() + b"\x00"
        elif b"connect" in lowered:
            reply = b"connectResponse\x00"
        rows.append({"peer": list(peer), "len": len(data),
                     "head": data[:32].hex(), "text": text.decode("latin-1"),
                     "reply": reply.decode("latin-1") if reply else None})
        if reply:
            sock.sendto(reply, peer)
    sock.close()
    text = json.dumps({"schema": 1, "port": args.port,
                       "utc": datetime.now(timezone.utc).isoformat(),
                       "packets": len(rows), "rows": rows},
                      ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
