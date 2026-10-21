#!/usr/bin/env python
"""Minimal 1649370 lab server: getchallenge/connect/stats/usermove.

This is a private prototype, not a modification of the community server. It
implements the text handshake observed on the 2697 reference and logs every
packet so a future 1649370 client/gamestate adapter can be verified.
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path

OOB = b"\xff\xff\xff\xff"
DEFAULT_XUID = "a731af49a6a2c7e2"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=28969)
    parser.add_argument("--map", default="mp_cross_fire")
    parser.add_argument("--gametype", default="war")
    parser.add_argument("--gamestate", type=Path,
                        default=Path("runs/2697-gamestate-packets/gamestate-final.bin"))
    parser.add_argument("--log", type=Path, default=Path("runs/mini-1649370-server.log.jsonl"))
    args = parser.parse_args()

    args.log.parent.mkdir(parents=True, exist_ok=True)
    log = args.log.open("a", encoding="utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.5)
    print(f"listening {args.host}:{args.port} map={args.map}", flush=True)
    started = time.time()
    state: dict[str, dict] = {}
    try:
        while True:
            try:
                data, peer = sock.recvfrom(65535)
            except socket.timeout:
                continue
            now = time.time()
            entry = {"t": round(now - started, 3), "peer": peer, "len": len(data), "hex": data.hex()}
            if data.startswith(OOB):
                body = data[4:]
                if body.startswith(b"getchallenge"):
                    cookie = f"{int(now) & 0x7fffffff:08x}"
                    state[peer[1]] = {"cookie": cookie}
                    reply = OOB + b"challengeResponse " + cookie.encode()
                    sock.sendto(reply, peer)
                    entry.update({"kind": "getchallenge", "cookie": cookie})
                elif body.startswith(b"connect"):
                    cookie = state.get(peer[1], {}).get("cookie", "0")
                    reply = (OOB + b"connectResponse \\mapname\\" + args.map.encode() +
                             b"\\gametype\\" + args.gametype.encode() +
                             b"\\sv_maxclients\\12\\protocol\\1\\shortversion\\1.1.1.13")
                    sock.sendto(reply, peer)
                    entry.update({"kind": "connect", "cookie": cookie,
                                  "request_ascii": body.decode("latin-1", "replace")})
                elif body.startswith(b"stats"):
                    index = body[5] if len(body) > 5 else -1
                    sock.sendto(OOB + b"statResponse", peer)
                    entry.update({"kind": "stats", "index": index})
                else:
                    entry.update({"kind": "oob-other", "body": body.decode("latin-1", "replace")})
            else:
                entry.update({"kind": "payload"})
                # A real client sends usermove here; reply with the captured gamestate
                # only when explicitly requested, because the 1649370 framing differs.
                if data and data[0] == 1 and args.gamestate.exists():
                    entry["note"] = "usermove-like packet; gamestate not sent by this prototype"
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
