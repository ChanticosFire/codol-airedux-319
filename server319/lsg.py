"""HTTPS lobby (LSG) endpoint scaffold for Build 1649370.

The client's LSG URL template was recovered from the EXE data section:

    %s://%s:%d/%s/title/%d/queue/%d/member/%llu

with ``https`` and ``v1.0`` constants, so the lobby channel is HTTPS on the
port from ``dwauth.ini`` line 1 (observed value 4174). No live LSG request has
been captured yet: the client reaches it only after an elevated IIPS run, the
ticket-gate patch and a UI/state-machine step.

This server therefore does not pretend to implement the lobby. It accepts the
TLS connection (legacy suites, same as Auth), records the request path, headers,
body length and SHA-256, and answers 404 so the client's own behavior remains
the oracle. When a real request is captured, its shape can be turned into a
contract here with tests.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from pathlib import Path

from .auth import AuthEvidence, AuthServer, parse_request

LSG_NOT_IMPLEMENTED = b'{"error":"lsg-not-implemented"}'


class LsgServer(AuthServer):
    """Same TLS/HTTP plumbing as Auth, but a lobby-shaped response."""

    def _handle(self, conn: socket.socket) -> None:
        session = self._new_session()
        try:
            head = conn.recv(16, socket.MSG_PEEK)
        except OSError:
            head = b""
        if head and head[0] not in (0x16, 0x80):
            self.evidence.write("plaintext_connect", session, client=str(conn.getpeername()[0]),
                                request_line=f"first_byte=0x{head[0]:02x}")
            try:
                conn.settimeout(5)
                data = conn.recv(4096)
                if data:
                    self.evidence.write("plaintext_frame", session, body_len=len(data),
                                        body_sha256=hashlib.sha256(data).hexdigest())
            except OSError:
                pass
            finally:
                conn.close()
            return
        try:
            tls = self.context.wrap_socket(conn, server_side=True)
        except Exception as exc:
            self.evidence.write("tls_handshake_failed", session, reason=type(exc).__name__)
            conn.close()
            return
        try:
            raw = b""
            tls.settimeout(12)
            while b"\r\n\r\n" not in raw:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                raw += chunk
            head, _, rest = raw.partition(b"\r\n\r\n")
            lines = head.decode("latin-1", "replace").split("\r\n")
            headers = {}
            for line in lines[1:]:
                if ": " in line:
                    key, _, value = line.partition(": ")
                    headers[key.lower()] = value
            length = int(headers.get("content-length") or 0)
            body = rest
            if headers.get("expect", "").lower() == "100-continue":
                tls.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            while len(body) < length:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                body += chunk
            body = body[:length] if length else body
            session.requests += 1
            self.evidence.write("lsg_request", session, request_line=lines[0],
                                headers=lines[1:40], body_len=len(body),
                                body_sha256=hashlib.sha256(body).hexdigest())
            response = (
                b"HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(LSG_NOT_IMPLEMENTED)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + LSG_NOT_IMPLEMENTED
            )
            tls.sendall(response)
            self.evidence.write("lsg_response", session, status=404, response_len=len(response))
        except Exception as exc:
            self.evidence.write("io_error", session, reason=type(exc).__name__)
        finally:
            try:
                tls.close()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build 1649370 LSG capture scaffold")
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    server = LsgServer(args.port, args.cert, args.key, AuthEvidence(args.log))
    server.start()
    print(f"LSG scaffold listening 127.0.0.1:{args.port} for {args.seconds:g}s", flush=True)
    try:
        server.serve(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
