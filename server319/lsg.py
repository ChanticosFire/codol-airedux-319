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
                                reply83 = b"\xab\x83" + challenge + b"\x00" * 6
                                frame83 = struct.pack("<I", len(reply83)) + reply83
                                conn.sendall(frame83)
                                self.evidence.write("token_reply", session,
                                                    reply_hex=frame83.hex())
                                # Keep reading: the client may answer with the
                                # 0x85 encrypted channel frame right after.
                                try:
                                    conn.settimeout(10)
                                    after = conn.recv(8192)
                                    if after:
                                        self.evidence.write("plaintext_frame3", session,
                                                            body_len=len(after),
                                                            body_sha256=hashlib.sha256(after).hexdigest(),
                                                            body_hex=after[:512].hex())
                                        # 0x85 carries the AES channel: conn+0x604/0x608
                                        # hold POINTERS; the 16-byte key lives at [ptr+0x9C].
                                        # 0x604 decrypts the client's frames (verified:
                                        # it yields the 84-byte 0x86 login request);
                                        # 0x608 encrypts our replies.
                                        try:
                                            from Crypto.Cipher import AES
                                            from . import lsg_client as _lc
                                            _pids = _lc.find_client_pids()
                                            if not _pids:
                                                raise RuntimeError("no-client")
                                            _pid = _pids[0]
                                            _ks = _lc.read_u32(_pid, caddr + 0x604)
                                            _kr = _lc.read_u32(_pid, caddr + 0x608)
                                            if not _ks or not _kr:
                                                raise RuntimeError("no-key-ptr")
                                            key_send = bytes.fromhex(_lc.read_region(_pid, _ks + 0x9C, 16))
                                            key_recv = bytes.fromhex(_lc.read_region(_pid, _kr + 0x9C, 16))
                                            if after[:6][4:6] == b"\xab\x85":
                                                seq = after[6:10]
                                                iv = after[10:26]
                                                cipher = after[26:-8]
                                                pt = AES.new(key_send, AES.MODE_CBC, iv=iv).decrypt(cipher)
                                                self.evidence.write("frame85_plain", session,
                                                                    body_hex=pt.hex())
                                                # Experiment: echo the client's own request as
                                                # the heartbeat payload (lsg_echo319 uses an
                                                # externally supplied pt; echo is the safest probe).
                                                echo_pt = pt + b"\x00" * ((-len(pt)) % 16)
                                                # Reply with a business frame carrying the
                                                # tag 0x0A lobby address (IP 4B + PORT 4B),
                                                # which the client's 0xB83A52 path turns into
                                                # netobj+0x4F8 = 1 (lobby ready).
                                                ip = bytes([127, 0, 0, 1])
                                                port = struct.pack("<I", 4174)
                                                tlv = b"\x0a\x08" + ip + port
                                                # Business frame type 4 is the tag 0x0A
                                                # lobby-address branch (0xB83A4B); 0x86 is the
                                                # client->server hardware-fingerprint type and
                                                # lands in the dispatcher default error path.
                                                inner = b"\x04" + tlv
                                                pt = struct.pack("<I", len(inner)) + inner
                                                pt += b"\x00" * ((-len(pt)) % 16)
                                                # The client expects our frame counter to equal
                                                # its conn+0x5EC (rxseq), not an echo of its own seq.
                                                _rxseq = _lc.read_u32(_pid, caddr + 0x5EC) or 1
                                                # Reference (lsg_echo319 heartbeat) keeps sending
                                                # 0x85 every ~2s; a single reply times out.
                                                for _beat in range(8):
                                                    riv = os.urandom(16)
                                                    rct = AES.new(key_recv, AES.MODE_CBC,
                                                                  iv=riv).encrypt(pt)
                                                    # Reference heartbeat reuses the SAME counter
                                                    # (exp) every 2s; do not increment.
                                                    seq_out = struct.pack("<I", _rxseq)
                                                    reply = (b"\x01\x85" + seq_out + riv + rct
                                                             + b"\x00" * 8)
                                                    conn.sendall(struct.pack("<I", len(reply)) + reply)
                                                    self.evidence.write(
                                                        "frame85_reply", session,
                                                        body_hex=pt.hex(),
                                                        reply_hex=reply.hex(),
                                                        reason=f"beat={_beat} seq={_rxseq + _beat}")
                                                    time.sleep(2.0)
                                                # Keep the channel open and log whatever
                                                # the client sends next (heartbeats/business).
                                                try:
                                                    conn.settimeout(12)
                                                    for _n in range(4):
                                                        _more = conn.recv(8192)
                                                        if not _more:
                                                            break
                                                        self.evidence.write(
                                                            "plaintext_frame4", session,
                                                            body_len=len(_more),
                                                            body_sha256=hashlib.sha256(_more).hexdigest(),
                                                            body_hex=_more[:512].hex())
                                                except OSError:
                                                    pass
                                        except Exception as _exc:
                                            self.evidence.write("key_error", session,
                                                                reason=type(_exc).__name__)
                                except OSError:
                                    pass
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
