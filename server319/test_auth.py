"""Synthetic tests for the Auth endpoint contract (no network, no client)."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from server319 import auth


CAPTURED_REQUEST = {
    "auth_task": "10",
    "iv_seed": "2696046749",
    "title_id": "1002",
    "identity": "356c4bc3",
    "extra_data": "{\"version\": \"0\", \"user_id\": \"934477427295145000\", \"extended_data\": true}",
}


class BuildResponseTests(unittest.TestCase):
    def test_observed_fields(self):
        response = auth.build_response(CAPTURED_REQUEST)
        self.assertEqual(response["result"], 700)
        self.assertEqual(response["code"], 700)
        self.assertTrue(response["success"])
        self.assertEqual(response["auth_task"], "11")
        self.assertEqual(response["iv_seed"], "2696046749")
        self.assertEqual(response["title_id"], "1002")
        self.assertEqual(response["license_id"], 1002)
        self.assertEqual(response["user_id"], "934477427295145000")
        self.assertEqual(response["identity"], "356c4bc3")
        for key in ("server_ticket", "client_ticket", "lsg_server_ticket"):
            self.assertEqual(len(base64.b64decode(response[key])), 128)
            self.assertEqual(response[key + "_size"], 128)

    def test_missing_extra_data_is_tolerated(self):
        response = auth.build_response({"auth_task": "10"})
        self.assertEqual(response["user_id"], "0")
        self.assertEqual(response["license_id"], 1002)
        self.assertEqual(response["iv_seed"], "0")

    def test_queue_admission_fields_survive_wire_encoding(self):
        response = json.loads(json.dumps(auth.build_response(CAPTURED_REQUEST)))
        for key in ("member_position", "estimated_wait_time", "next_poll_after"):
            self.assertIs(type(response[key]), int)
            self.assertEqual(response[key], 0)

    def test_bad_extra_data_is_tolerated(self):
        response = auth.build_response({"extra_data": "not json", "title_id": "1002"})
        self.assertEqual(response["user_id"], "0")

    def test_headers_carry_dw_fields(self):
        headers = auth.build_response_headers(CAPTURED_REQUEST, 100)
        text = headers.decode("latin-1")
        for name in ("DW-Server-Ticket:", "DW-Server-Ticket-Size: 128",
                     "DW-Client-Ticket:", "DW-Client-Ticket-Size: 128",
                     "DW-Ticket-Seed: 2696046749", "Content-Length: 100"):
            self.assertIn(name, text)


class ParseRequestTests(unittest.TestCase):
    def test_valid_json(self):
        self.assertEqual(auth.parse_request(json.dumps(CAPTURED_REQUEST).encode()), CAPTURED_REQUEST)

    def test_non_json(self):
        self.assertEqual(auth.parse_request(b"\x00\x01\x02"), {})

    def test_json_array_is_rejected(self):
        self.assertEqual(auth.parse_request(b"[1,2]"), {})


class EvidenceTests(unittest.TestCase):
    def test_disallowed_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = auth.AuthEvidence(Path(tmp) / "auth.jsonl")
            session = auth.Session(connection_id=1)
            with self.assertRaises(ValueError):
                evidence.write("x", session, ticket="secret")

    def test_allowed_fields_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.jsonl"
            evidence = auth.AuthEvidence(path)
            evidence.write("auth_request", auth.Session(connection_id=1), body_len=10,
                           body_sha256="00", request_line="POST /auth/ HTTP/1.1")
            record = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["event"], "auth_request")
            self.assertEqual(record["body_len"], 10)


if __name__ == "__main__":
    unittest.main()
