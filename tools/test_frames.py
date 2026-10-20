"""Offline structural tests for the bdMatchMaking reply frames.

These lock down the wire format of the two frames the lobby will need once the
client asks for them, so a regression is caught without needing a running client:

  svc71/task9  FindSessions  - one bdMatchMaking server entry
  svc21/task5  session list  - same entry, different service/task bytes

Run:
    python -m unittest tools.test_frames -v
"""
from __future__ import annotations

import struct
import unittest

from server319.lsg_derived import (
    _typed_string,
    _typed_u16,
    _typed_u32,
    _typed_u64,
    candidate_svc71_task9_reply,
    make_server_entry,
)

# typed-value tags used by the bdService codec
TAG_U32 = 0x08
TAG_U16 = 0x06
TAG_STRING = 0x10
TAG_U64 = 0x0a


def parse_typed(blob: bytes) -> list[tuple[int, object]]:
    """Decode the typed-value stream so tests can assert on field values."""
    out: list[tuple[int, object]] = []
    i = 0
    while i < len(blob):
        tag = blob[i]
        i += 1
        if tag == TAG_U32:
            out.append((tag, struct.unpack_from("<I", blob, i)[0]))
            i += 4
        elif tag == TAG_U16:
            out.append((tag, struct.unpack_from("<H", blob, i)[0]))
            i += 2
        elif tag == TAG_U64:
            out.append((tag, struct.unpack_from("<Q", blob, i)[0]))
            i += 8
        elif tag == TAG_STRING:
            # 0x10 tag + NUL-terminated bytes (no length prefix)
            end = blob.index(b"\x00", i)
            out.append((tag, blob[i:end]))
            i = end + 1
        elif tag == 0x03:
            # bare service/task pair, no typed wrapper
            out.append((0x03, blob[i:i + 1]))
            i += 1
        else:
            # unknown framing (e.g. a trailing raw field): stop parsing
            out.append((0xFF, tag))
            break
    return out


class TestServerEntry(unittest.TestCase):
    def test_default_length_is_114(self) -> None:
        self.assertEqual(len(make_server_entry()), 114)

    def test_length_scales_with_name(self) -> None:
        base = len(make_server_entry(name=b""))
        for n in (1, 5, 20):
            self.assertEqual(len(make_server_entry(name=b"x" * n)), base + n)

    def test_first_fields_are_ip_and_port(self) -> None:
        entry = make_server_entry(ip=b"\x7f\x00\x00\x01", port=8466)
        fields = parse_typed(entry)
        self.assertEqual(fields[0], (TAG_U32, 0x0100007F))  # 127.0.0.1 LE
        self.assertEqual(fields[1], (TAG_U16, 8466))

    def test_contains_server_name(self) -> None:
        entry = make_server_entry(name=b"Alpha")
        fields = parse_typed(entry)
        strings = [v for t, v in fields if t == TAG_STRING]
        self.assertIn(b"Alpha", strings)

    def test_name_round_trips_exactly(self) -> None:
        for name in (b"A", b"TestServer", b"server-with-dashes", b"x" * 40):
            entry = make_server_entry(name=name)
            strings = [v for t, v in parse_typed(entry) if t == TAG_STRING]
            self.assertEqual(strings, [name])

    def test_ip_is_repeated_for_the_probe_address(self) -> None:
        entry = make_server_entry(ip=b"\x0a\x00\x00\x05", port=1234)
        fields = parse_typed(entry)
        u32s = [v for t, v in fields if t == TAG_U32]
        self.assertEqual(u32s[0], 0x0500000A)
        # the address is also repeated later in the entry
        self.assertGreaterEqual(u32s.count(0x0500000A), 2)

    def test_zero_ip_is_allowed(self) -> None:
        entry = make_server_entry(ip=b"\x00\x00\x00\x00")
        self.assertEqual(len(entry), 114)
        self.assertEqual(parse_typed(entry)[0], (TAG_U32, 0))


class TestFindSessionsReply(unittest.TestCase):
    def test_header_and_count(self) -> None:
        reply = candidate_svc71_task9_reply(transaction_id=7, port=8466)
        # the transaction id is a typed u64: 0x0a tag then 8 bytes
        self.assertEqual(reply[0], TAG_U64)
        tid = struct.unpack_from("<Q", reply, 1)[0]
        self.assertEqual(tid, 7)
        # after the u64 transaction id and a typed u32 comes the service/task pair
        self.assertIn(b"\x03\x09", reply)

    def test_grows_with_entry(self) -> None:
        reply = candidate_svc71_task9_reply(1, 8466)
        entry = make_server_entry(port=8466)
        # u64(9) + u32(5) + bare service/task(2) + u32(5) + u32(5) + entry
        self.assertEqual(len(reply), len(entry) + 26)

    def test_embeds_the_same_entry_bytes(self) -> None:
        reply = candidate_svc71_task9_reply(1, 8466)
        entry = make_server_entry(port=8466)
        self.assertTrue(reply.endswith(entry))

    def test_distinct_transaction_ids_differ(self) -> None:
        a = candidate_svc71_task9_reply(1, 8466)
        b = candidate_svc71_task9_reply(2, 8466)
        self.assertNotEqual(a[:9], b[:9])
        self.assertEqual(a[9:], b[9:])

    def test_port_is_carried_through(self) -> None:
        for port in (1, 3074, 8466, 65535):
            reply = candidate_svc71_task9_reply(1, port)
            strings = [v for t, v in parse_typed(reply) if t == TAG_STRING]
            self.assertTrue(strings, f"no string field for port {port}")
            self.assertIn(struct.pack("<H", port), reply)


class TestTypedCodec(unittest.TestCase):
    def test_u32(self) -> None:
        self.assertEqual(_typed_u32(0x12345678), b"\x08\x78\x56\x34\x12")

    def test_u16(self) -> None:
        self.assertEqual(_typed_u16(0x1234), b"\x06\x34\x12")

    def test_string_is_nul_terminated(self) -> None:
        self.assertEqual(_typed_string(b"AB"), b"\x10AB\x00")

    def test_empty_string(self) -> None:
        self.assertEqual(_typed_string(b""), b"\x10\x00")

    def test_u64_has_its_own_tag_and_is_eight_bytes(self) -> None:
        self.assertEqual(_typed_u64(1), b"\x0a" + struct.pack("<Q", 1))
        self.assertEqual(len(_typed_u64(1)), 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
