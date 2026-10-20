"""Build 1649370 LSG responder using transcript-derived session keys.

The handshake and client-frame verifier are qualified by local captures. Task
responses below are explicitly provisional until consumed by the target client.
Unknown requests remain visible in the run log and receive no fake success.
"""

from __future__ import annotations

import hashlib
import os
import socket
import struct
import threading
import time

from .auth import AuthServer
from .lsg_crypto import (LsgProtocolError, build_server_frame85, derive_keys,
                         parse_client_frame85)
from .ticket import SESSION_KEY

GATE_MARK = 0x1122334455667788
MAX_FRAME = 1 << 20


def _read_exact(conn: socket.socket, size: int) -> bytes:
    out = bytearray()
    while len(out) < size:
        part = conn.recv(size - len(out))
        if not part:
            raise EOFError("peer_closed")
        out.extend(part)
    return bytes(out)


def _read_frame(conn: socket.socket) -> bytes:
    head = _read_exact(conn, 4)
    size = struct.unpack("<I", head)[0]
    if size > MAX_FRAME:
        raise LsgProtocolError("oversize_frame")
    return head + _read_exact(conn, size) if size else head


def _typed_u32(value: int) -> bytes:
    return b"\x08" + struct.pack("<I", value)


def _typed_u64(value: int) -> bytes:
    return b"\x0a" + struct.pack("<Q", value)


def candidate_svc71_task4_reply(transaction_id: int = 1) -> bytes:
    """Candidate bdService envelope from local reference; unconsumed on 1649370."""
    return (_typed_u64(transaction_id) + _typed_u32(0) + b"\x03\x04"
            + _typed_u32(1) + _typed_u32(1) + _typed_u32(0))


def candidate_empty_success_reply(transaction_id: int, task_id: int) -> bytes:
    """1604220 lobby fallback shape, provisional for observed 1649370 tasks."""
    if not 0 <= task_id <= 255:
        raise LsgProtocolError("candidate_task_id")
    return _typed_u64(transaction_id) + _typed_u32(0) + b"\x03" + bytes([task_id]) + _typed_u32(0)


def _typed_u16(value: int) -> bytes:
    return b"\x06" + struct.pack("<H", value)


def _typed_string(text: bytes) -> bytes:
    """0x10 tag + NUL-terminated bytes (bdsvc319's string encoding)."""
    return b"\x10" + text + b"\x00"


def make_server_entry(ip: bytes = b"\x7f\x00\x00\x01", port: int = 8466,
                      name: bytes = b"TestServer") -> bytes:
    """bdMatchMaking server entry, byte-for-byte as bdsvc319.make_server_entry.

    114 bytes when the name is TestServer. bdsvc319 builds it with the same
    typed-value codec this module already uses (0x08 u32, 0x06 u16, 0x10 str).
    """
    out = bytearray()
    out += _typed_u32(struct.unpack("<I", ip)[0])
    out += _typed_u16(port)
    out += _typed_u16(0)
    for _ in range(5):
        out += _typed_u32(0)
    out += _typed_u32(0x9D)
    for _ in range(5):
        out += _typed_u32(0)
    out += _typed_u32(1)
    out += _typed_u32(1)
    out += _typed_string(name)
    out += _typed_u32(0)
    out += _typed_u32(struct.unpack("<I", ip)[0])
    out += _typed_u16(port)
    out += _typed_u16(0)
    out += _typed_u32(0)
    out += _typed_u32(0)
    return bytes(out)


def candidate_svc71_task9_reply(transaction_id: int = 1,
                                port: int = 8466) -> bytes:
    """svc71/task9 FindSessions: one bdMatchMaking entry for 127.0.0.1:port."""
    entry = make_server_entry(port=port)
    return (_typed_u64(transaction_id) + _typed_u32(0) + b"\x03\x09"
            + _typed_u32(1) + _typed_u32(1) + entry)


def terminal_unavailable_reply(transaction_id: int) -> bytes:
    """14-byte bdService error candidate; no fabricated result object."""
    return _typed_u64(transaction_id) + _typed_u32(14)


class DerivedLsgServer(AuthServer):
    def __init__(self, *args, token_marker: int = 0x00,
                 observed71_empty: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if token_marker not in (0x00, 0xAB):
            raise ValueError("token_marker")
        self.token_marker = token_marker
        self.observed71_empty = observed71_empty

    def _handle(self, conn: socket.socket) -> None:
        session = self._new_session()
        try:
            conn.settimeout(10)
            head = conn.recv(16, socket.MSG_PEEK)
            if head and head[0] in (0x16, 0x80):
                self.evidence.write("unsupported_tls_lsg", session)
                return
            hello = _read_exact(conn, 28)
            self.evidence.write("plaintext_frame", session, body_len=len(hello),
                                body_sha256=hashlib.sha256(hello).hexdigest(),
                                body_hex=hello.hex())
            gate_body = (b"\x01\x81" + struct.pack("<I", 220)
                         + struct.pack("<Q", GATE_MARK) + os.urandom(8))
            gate = struct.pack("<I", len(gate_body)) + gate_body
            conn.sendall(gate)
            self.evidence.write("gate_reply", session, reply_hex=gate.hex())
            client_auth = _read_frame(conn)
            self.evidence.write("plaintext_frame2", session,
                                body_len=len(client_auth),
                                body_sha256=hashlib.sha256(client_auth).hexdigest(),
                                body_hex=client_auth.hex())
            keys = derive_keys(hello, gate, client_auth, SESSION_KEY)
            self.evidence.write("session_derived", session,
                                reason="challenge_verified; client-memory-read=false")
            token = (struct.pack("<I", 10) + bytes([self.token_marker, 0x83])
                     + keys.challenge[8:])
            conn.sendall(token)
            self.evidence.write("token_reply", session, reply_hex=token.hex())
            counter = 1
            # PROGRESS.md: the reference server pushes a ZEROFRAME (bare u32 0)
            # every 30 s to keep the lobby alive. Send it from a helper thread so
            # the recv loop stays blocking.
            idle_interval = float(os.environ.get("LSG_ZEROFRAME", "30"))
            stop_zero = threading.Event()

            def _zero_loop() -> None:
                while not stop_zero.wait(idle_interval):
                    try:
                        conn.sendall(bytes(4))
                        self.evidence.write("zero_frame", session)
                    except OSError:
                        return

            if idle_interval > 0:
                threading.Thread(target=_zero_loop, daemon=True).start()
            # The target remains silent after its first task while it waits for
            # further lobby state. A short recv timeout is a server-side close,
            # which the client surfaces as [100] after exactly that interval.
            conn.settimeout(75)
            while True:
                frame = _read_frame(conn)
                if frame == bytes(4):
                    # Zero-length control frame: the client's keepalive. Answer
                    # with the same bare u32 0 (lobby.py keeps the channel alive
                    # this way); staying silent makes it stall after task4.
                    self.evidence.write("idle_control", session)
                    if os.environ.get("LSG_IDLE_REPLY", "0") != "0":
                        conn.sendall(bytes(4))
                        self.evidence.write("idle_reply", session)
                    continue
                self.evidence.write("client_frame", session, body_len=len(frame),
                                    body_sha256=hashlib.sha256(frame).hexdigest(),
                                    body_hex=frame.hex())
                received_counter, inner_type, payload = parse_client_frame85(frame, keys)
                self.evidence.write("client_frame_verified", session,
                                    reason=f"counter={received_counter} inner={inner_type:#x} "
                                           f"payload_len={len(payload)}")
                if inner_type != 0x86 or len(payload) < 3:
                    self.evidence.write("unhandled_inner", session,
                                        reason=f"inner={inner_type:#x}")
                    continue
                service, tag, task = payload[:3]
                if tag != 0x03:
                    self.evidence.write("unhandled_task_header", session,
                                        reason=f"service={service} tag={tag:#x}")
                    continue
                self.evidence.write("task_request", session,
                                    reason=f"service={service} task={task} bytes={len(payload)}")
                if (service, task) == (71, 4):
                    reply_payload = candidate_svc71_task4_reply(counter)
                    reply = build_server_frame85(keys, reply_payload, counter=counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason="svc71/task4 reference candidate; client consumption unverified")
                    counter += 1
                elif (service, task) == (71, 9):
                    reply_payload = candidate_svc71_task9_reply(
                        counter, int(os.environ.get("FINDSESS_PORT", "8466")))
                    reply = build_server_frame85(keys, reply_payload, counter=counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason="svc71/task9 bdMatchMaking entry 127.0.0.1:%s; "
                                               "client consumption unverified"
                                               % os.environ.get("FINDSESS_PORT", "8466"))
                    counter += 1
                elif self.observed71_empty and service == 71 and task in (3, 7, 9):
                    reply = build_server_frame85(
                        keys, candidate_empty_success_reply(counter, task),
                        counter=counter, iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_empty_task_reply", session,
                                        reason=f"service=71 task={task}; 1604220 fallback "
                                               "shape; 1649370 consumption unverified")
                    counter += 1
                else:
                    self.evidence.write("unhandled_task", session,
                                        reason=f"service={service} task={task}")
                    reply = build_server_frame85(
                        keys, terminal_unavailable_reply(counter),
                        counter=counter, iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("terminal_task_reply", session,
                                        reason=f"service={service} task={task} error=14; "
                                               "candidate contract, consumption unverified")
                    counter += 1
        except (LsgProtocolError, EOFError, OSError, TimeoutError) as exc:
            self.evidence.write("raw_session_end", session,
                                reason=f"{type(exc).__name__}:{exc}")
        finally:
            try:
                conn.close()
            except OSError:
                pass
