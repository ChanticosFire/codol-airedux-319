"""Loopback capture service with per-connection state and no guessed replies."""

from __future__ import annotations

import hashlib
import json
import socketserver
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .framing import FrameError, FrameParser


@dataclass
class Session:
    connection_id: int
    opened_ns: int = field(default_factory=time.time_ns)
    frames_seen: int = 0
    phase: str = "connected"


class EvidenceLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event: str, session: Session, **fields: Any) -> None:
        # Never accept arbitrary wire data, credentials, tickets, or paths here.
        allow = {"body_len", "body_sha256", "reason", "buffered_bytes"}
        if set(fields) - allow:
            raise ValueError("evidence field not allowlisted")
        record = {"time_ns": time.time_ns(), "event": event,
                  "connection_id": session.connection_id,
                  "phase": session.phase, "frames_seen": session.frames_seen,
                  **fields}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        owner: LoopbackServer = self.server  # type: ignore[assignment]
        session = owner.new_session()
        parser = FrameParser()
        owner.evidence.write("connected", session)
        self.request.settimeout(5.0)
        try:
            while True:
                try:
                    chunk = self.request.recv(65536)
                except TimeoutError:
                    session.phase = "timeout"
                    owner.evidence.write("timeout", session,
                                         buffered_bytes=parser.buffered_bytes)
                    break
                if not chunk:
                    try:
                        parser.finish()
                    except FrameError as exc:
                        session.phase = "invalid"
                        owner.evidence.write("invalid_frame", session,
                                             reason=str(exc))
                    break
                try:
                    frames = parser.feed(chunk)
                except FrameError as exc:
                    session.phase = "invalid"
                    owner.evidence.write("invalid_frame", session,
                                         reason=str(exc))
                    break
                for frame in frames:
                    session.frames_seen += 1
                    session.phase = "unknown_message"
                    owner.evidence.write(
                        "unknown_message", session, body_len=len(frame.body),
                        body_sha256=hashlib.sha256(frame.body).hexdigest(),
                        reason="no verified Build 1649370 decoder or reply")
                    # Deliberately no response. A fabricated success can hide
                    # an incompatible client state or unimplemented protocol.
        finally:
            owner.evidence.write("closed", session)


class LoopbackServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, port: int, evidence: EvidenceLog):
        if not 0 <= port <= 65535:
            raise ValueError("invalid port")
        self.evidence = evidence
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)

    def new_session(self) -> Session:
        with self._sequence_lock:
            self._sequence += 1
            return Session(connection_id=self._sequence)
