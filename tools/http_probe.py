#!/usr/bin/env python
"""Minimal loopback HTTP capture server for IIPS/update probing.

Logs method, path, selected headers and body length for every request, then
answers 404 with an empty body. It never forwards anything upstream. Use it
together with an iips.ini that points at the listening port, so the client's
own request pattern becomes visible without any firewall change.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_LOCK = threading.Lock()


def make_handler(log_path: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _record(self, body: bytes) -> None:
            entry = {
                "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "method": self.command,
                "path": self.path,
                "headers": {key: value for key, value in self.headers.items()},
                "body_len": len(body),
                "body_sha256_prefix": __import__("hashlib").sha256(body).hexdigest()[:16] if body else "",
            }
            with LOG_LOCK:
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

        def _reply(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            self._record(body)
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            self._reply()

        def do_POST(self):
            self._reply()

        def do_HEAD(self):
            self._reply()

        def log_message(self, fmt, *args):
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.log))
    server.timeout = 1
    deadline = time.time() + args.seconds
    print(f"listening 127.0.0.1:{args.port} -> {args.log}", flush=True)
    while time.time() < deadline:
        server.handle_request()
    server.server_close()
    print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
