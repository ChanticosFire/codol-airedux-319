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
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

from .auth import AuthEvidence, AuthServer, parse_request

LSG_NOT_IMPLEMENTED = b'{"error":"lsg-not-implemented"}'
LSG_MARK = 0x1122334455667788  # reference handshake mark (lsg_echo319)

# 26-byte gate reply observed in the reference: [u32 22][01][81][u32 0xD2][8B mark][8B nonce]
LSG_GATE_OP = 0x81
LSG_GATE_VALUE = 0xD2


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
                                        body_sha256=hashlib.sha256(data).hexdigest(),
                                        body_hex=data[:256].hex())
                    # Answer the 28-byte hello with the 26-byte gate frame so the
                    # client advances to its 0x82 challenge instead of timing out.
                    nonce = os.urandom(8)
                    reply = (bytes([0x01, LSG_GATE_OP])
                             + struct.pack("<I", LSG_GATE_VALUE)
                             + struct.pack("<Q", LSG_MARK) + nonce)
                    frame = struct.pack("<I", len(reply)) + reply
                    conn.sendall(frame)
                    self.evidence.write("gate_reply", session, reply_hex=frame.hex())
                    try:
                        conn.settimeout(8)
                        more = conn.recv(4096)
                        if more:
                            self.evidence.write("plaintext_frame2", session, body_len=len(more),
                                                body_sha256=hashlib.sha256(more).hexdigest(),
                                                body_hex=more[:256].hex())
                            # The client compares our 0x83 token against its own
                            # conn+0x5FC, so read that field out of the game.
                            try:
                                from . import lsg_client
                                pid, caddr, challenge = 0, 0, None
                                candidates = []
                                for candidate_pid in lsg_client.find_client_pids():
                                    candidates = lsg_client.find_service_conns(candidate_pid)
                                    if not candidates:
                                        candidates = lsg_client.find_conn_by_vtable(candidate_pid)
                                    if not candidates:
                                        candidates = lsg_client.find_conn_candidates(
                                            candidate_pid, LSG_MARK)
                                    if candidates:
                                        pid = candidate_pid
                                        break
                                if candidates:
                                    good = [c for c in candidates if c.get("stage") in (1, 2, 3)]
                                    pick = good[0] if good else candidates[0]
                                    caddr = pick["conn"]
                                    raw = bytes.fromhex(pick["challenge"])
                                    challenge = raw if len(raw) == 8 else None
                                    detail = [{"conn": hex(c["conn"]), "stage": c.get("stage"),
                                               "challenge": c.get("challenge")} for c in candidates[:4]]
                                    self.evidence.write("challenge_detail", session,
                                                        reason=json.dumps(detail)[:600])
                                    if caddr:
                                        around = lsg_client.read_region(pid, caddr + 0x5F0, 0x20)
                                        self.evidence.write("conn_mem", session,
                                                            reason=f"{caddr:#x}+0x5F0 {around}")
                                self.evidence.write(
                                    "challenge_lookup", session,
                                    reason=f"pid={pid} candidates={len(candidates)} conn={caddr:#x}")
                            except Exception as exc:  # keep the listener alive
                                pid, caddr, challenge = 0, 0, None
                                self.evidence.write("challenge_error", session,
                                                    reason=type(exc).__name__)
                            self.evidence.write("challenge_choice", session,
                                                reason=f"token={challenge.hex() if challenge else None}")
                            if challenge:
                                reply83 = b"\xab\x83" + challenge + b"\x00\x00"
                                frame83 = struct.pack("<I", len(reply83)) + reply83
                                conn.sendall(frame83)
                                self.evidence.write("token_reply", session,
                                                    reply_hex=frame83.hex())
                    except OSError:
                        pass
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
