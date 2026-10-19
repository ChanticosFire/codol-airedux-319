"""TLS Auth endpoint for Build 1649370.

The 1649370 client speaks HTTP JSON to ``POST /auth/`` over a legacy TLS
handshake (TLS 1.0/1.1/1.2 with old cipher suites; TLS 1.3 and default
OpenSSL security levels fail with ``NO_SUITABLE_SIGNATURE_ALGORITHM``).

This module is the production-shaped counterpart of the throw-away
``tools/lab_auth_server.py`` probe. It implements only what was actually
observed on the wire:

  request  {"auth_task":"10","iv_seed":"...","title_id":"1002",
            "identity":"356c4bc3","extra_data":"{...}"}
  response {"result":700,"code":0,"success":true,...,
            "server_ticket","client_ticket","lsg_server_ticket", ...}
  headers  DW-Server-Ticket, DW-Server-Ticket-Size, DW-Client-Ticket,
           DW-Client-Ticket-Size, DW-Ticket-Seed

Ticket bytes are zero-filled project-synthetic values: the real BD ticket key
and magic are unknown for this Build, and the client reaches the lobby only
after a runtime patch that skips its ticket verifier. The response shape is
still the part the client parses, so it is implemented and tested here.

Nothing in this module connects upstream, writes to the client or touches
protected regions. It binds 127.0.0.1 only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

TITLE_ID_DEFAULT = 1002
AUTH_RESULT_SUCCESS = 700
TICKET_BYTES = 128
ZERO_TICKET = base64.b64encode(b"\x00" * TICKET_BYTES).decode()


def build_response(request: dict) -> dict:
    """Return the JSON object the client expects for /auth/ (observed shape)."""
    title_id = request.get("title_id", str(TITLE_ID_DEFAULT))
    try:
        license_id = int(title_id)
    except (TypeError, ValueError):
        license_id = TITLE_ID_DEFAULT
    user_id = "0"
    extra_data = request.get("extra_data")
    if isinstance(extra_data, str):
        try:
            user_id = str(json.loads(extra_data).get("user_id", "0"))
        except (ValueError, AttributeError):
            user_id = "0"
    response = {
        "result": AUTH_RESULT_SUCCESS,
        "code": 0,
        "success": True,
        "iv_seed": str(request.get("iv_seed", "0")),
        "server_ticket": ZERO_TICKET,
        "server_ticket_size": TICKET_BYTES,
        "lsg_server_ticket": ZERO_TICKET,
        "lsg_server_ticket_size": TICKET_BYTES,
        "client_ticket": ZERO_TICKET,
        "client_ticket_size": TICKET_BYTES,
        "time_to_live": 3600,
        "licenses": [],
        "license_id": license_id,
        "cd_key": "",
        "ciphertext": "",
        "extra_data": "{}",
        "user_id": user_id,
        "identity": request.get("identity", "356c4bc3"),
        "title_id": title_id,
    }
    if request.get("auth_task") is not None:
        response["auth_task"] = request["auth_task"]
    return response


def build_response_headers(request: dict, body_length: int) -> bytes:
    """DW-* headers mirroring the observed reference shape."""
    seed = str(request.get("iv_seed", "0")).encode()
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"DW-Server-Ticket: " + ZERO_TICKET.encode() + b"\r\n"
        b"DW-Server-Ticket-Size: 128\r\n"
        b"DW-Client-Ticket: " + ZERO_TICKET.encode() + b"\r\n"
        b"DW-Client-Ticket-Size: 128\r\n"
        b"DW-Ticket-Seed: " + seed + b"\r\n"
        b"Content-Length: " + str(body_length).encode() + b"\r\n"
        b"Connection: keep-alive\r\n\r\n"
    )


def parse_request(body: bytes) -> dict:
    """Best-effort JSON decode; never raises."""
    try:
        value = json.loads(body.decode("utf-8", "replace"))
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


@dataclass
class Session:
    connection_id: int
    opened_utc: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    requests: int = 0


class AuthEvidence:
    """Append-only JSONL evidence; never records ticket bytes or bodies verbatim."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: str, session: Session, **fields) -> None:
        allowed = {"request_line", "headers", "body_len", "body_sha256", "status",
                   "response_len", "reason", "client"}
        extra = set(fields) - allowed
        if extra:
            raise ValueError(f"evidence field not allowlisted: {sorted(extra)}")
        record = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "event": event, "connection_id": session.connection_id,
                  "requests": session.requests, **fields}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


class AuthServer:
    def __init__(self, port: int, cert: Path, key: Path, evidence: AuthEvidence,
                 ciphers: str = "ALL:@SECLEVEL=0"):
        self.port = port
        self.evidence = evidence
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(str(cert), str(key))
        try:
            self.context.set_ciphers(ciphers)
        except ssl.SSLError:
            pass
        self.context.minimum_version = ssl.TLSVersion.TLSv1
        self.context.maximum_version = ssl.TLSVersion.TLSv1_2
        self.context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        self._server: socket.socket | None = None
        self._sequence = 0
        self._lock = threading.Lock()

    def _new_session(self) -> Session:
        with self._lock:
            self._sequence += 1
            return Session(connection_id=self._sequence)

    def start(self) -> None:
        server = socket.create_server(("127.0.0.1", self.port))
        server.settimeout(1.0)
        self._server = server

    def serve(self, seconds: float) -> None:
        if self._server is None:
            raise RuntimeError("start() first")
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            thread = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            thread.start()

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    def _handle(self, conn: socket.socket) -> None:
        session = self._new_session()
        try:
            head = conn.recv(16, socket.MSG_PEEK)
        except OSError:
            head = b""
        if head and head[0] not in (0x16, 0x80):
            # Plaintext lobby frame layer (observed as a second connection on
            # the same port on the 1604220 reference). Capture metadata only.
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
            request = parse_request(body)
            session.requests += 1
            self.evidence.write("auth_request", session, request_line=lines[0],
                                headers=lines[1:40], body_len=len(body),
                                body_sha256=hashlib.sha256(body).hexdigest())
            response = build_response(request)
            payload = json.dumps(response).encode()
            tls.sendall(build_response_headers(request, len(payload)) + payload)
            self.evidence.write("auth_response", session, status=200, response_len=len(payload))
        except Exception as exc:
            self.evidence.write("io_error", session, reason=type(exc).__name__)
        finally:
            try:
                tls.close()
            except OSError:
                pass
