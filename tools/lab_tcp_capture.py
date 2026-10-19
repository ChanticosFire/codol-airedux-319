#!/usr/bin/env python
"""Raw TCP capture listener for the 1649370 lobby (LSG) port.

Records the first bytes of every connection as hex and text, without answering
(beyond an optional echo). Use it to learn whether the client connects to the
port configured in dwauth.ini and what its opening frame looks like.

Usage:
  python tools/lab_tcp_capture.py --port 4174 --log runs/<id>/lsg.jsonl --seconds 120
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from pathlib import Path

LOCK = threading.Lock()
LOG_PATH: Path | None = None


def record(entry: dict) -> None:
    entry["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with LOCK:
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def handle(conn: socket.socket) -> None:
    record({"event": "connected"})
    data = b""
    try:
        conn.settimeout(8)
        while len(data) < 65536:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            record({"event": "recv", "bytes": len(chunk), "total": len(data), "hex": chunk[:512].hex()})
            if len(data) >= 4096:
                break
        if data:
            record({"event": "summary", "total": len(data), "hex": data[:1024].hex(),
                    "text": data[:512].decode("latin-1", "replace")})
            conn.sendall(data[:64])  # echo the first 64 bytes as a crude probe
            record({"event": "echoed", "bytes": 64})
    except Exception as exc:
        record({"event": "error", "error": type(exc).__name__, "detail": str(exc)[:200]})
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    global LOG_PATH
    LOG_PATH = args.log.resolve()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")
    server = socket.create_server(("127.0.0.1", args.port))
    server.settimeout(1)
    deadline = time.time() + args.seconds
    print(f"tcp capture listening 127.0.0.1:{args.port}", flush=True)
    while time.time() < deadline:
        try:
            conn, _addr = server.accept()
        except socket.timeout:
            continue
        threading.Thread(target=handle, args=(conn,), daemon=True).start()
    server.close()
    print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
