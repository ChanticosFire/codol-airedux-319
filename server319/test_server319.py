"""Synthetic tests only; no game files or client processes required."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from server319.framing import FrameError, FrameParser
from server319.manifest import ANCHORS, verify_client
from server319.service import EvidenceLog, LoopbackServer, Session


class ManifestTests(unittest.TestCase):
    def test_missing_anchors_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            checks = verify_client(Path(temp))
        self.assertEqual(len(checks), len(ANCHORS))
        self.assertTrue(all(not check.ok and check.reason == "missing" for check in checks))

    def test_wrong_size_fails_without_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "codoMP_client_shipRetail.exe").write_bytes(b"wrong")
            checks = verify_client(Path(temp))
        self.assertEqual(checks[0].reason, "size_mismatch")
        self.assertIsNone(checks[0].actual_sha256)


class FrameTests(unittest.TestCase):
    def test_fragmented_and_batched_frames(self) -> None:
        p = FrameParser()
        self.assertEqual(p.feed(b"\x03\x00"), [])
        self.assertEqual(p.feed(b"\x00\x00a"), [])
        frames = p.feed(b"bc\x01\x00\x00\x00z")
        self.assertEqual([f.body for f in frames], [b"abc", b"z"])
        p.finish()

    def test_zero_oversized_and_truncated_rejected(self) -> None:
        with self.assertRaises(FrameError):
            FrameParser().feed(bytes(4))
        with self.assertRaises(FrameError):
            FrameParser(max_body=4).feed((5).to_bytes(4, "little"))
        p = FrameParser()
        p.feed(b"\x02\x00\x00\x00a")
        with self.assertRaises(FrameError):
            p.finish()


class ServiceTests(unittest.TestCase):
    def test_unknown_message_logged_without_wire_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.jsonl"
            with LoopbackServer(0, EvidenceLog(path)) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with socket.create_connection(server.server_address, timeout=2) as client:
                    client.settimeout(0.2)
                    client.sendall(b"\x06\x00\x00\x00SECRET")
                    with self.assertRaises(socket.timeout):
                        client.recv(1)
                server.shutdown()
                thread.join(timeout=2)
            raw = path.read_text(encoding="utf-8")
            rows = [json.loads(line) for line in raw.splitlines()]
        self.assertNotIn("SECRET", raw)
        self.assertIn("unknown_message", [row["event"] for row in rows])
        self.assertEqual(next(row for row in rows if row["event"] == "unknown_message")["body_len"], 6)

    def test_evidence_rejects_unapproved_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log = EvidenceLog(Path(temp) / "evidence.jsonl")
            with self.assertRaises(ValueError):
                log.write("bad", Session(1), password="secret")


if __name__ == "__main__":
    unittest.main()
