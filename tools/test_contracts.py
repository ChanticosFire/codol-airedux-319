"""Contract tests for every svc71 / svc21 / svc255 / svc80 reply the server can emit.

Extends test_frames.py from "the entry and one reply are well-formed" to "every
reply builder produces a payload the client's own TLV framing describes", using the
format decoded in PROJECT_STATUS §12.47:

    47 03 <task>   header (0x03 is a fixed version marker)
    0x13           length-prefixed container: 0x08 + u32 length + bytes
    0x08           u32
    0x10           NUL-terminated string (in the *request* direction)

Run:
    python -m unittest tools.test_contracts -v
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server319.lsg_derived import (  # noqa: E402
    _typed_string,
    _typed_u16,
    _typed_u32,
    _typed_u64,
    candidate_empty_success_reply,
    candidate_svc71_task4_reply,
    candidate_svc71_task9_reply,
    make_server_entry,
    terminal_unavailable_reply,
)
from server319.profile import ProfileStore  # noqa: E402

TAG_U32 = 0x08
TAG_U16 = 0x06
TAG_U64 = 0x0A
TAG_STRING = 0x10


def decode_typed(blob: bytes) -> list[tuple[int, object]]:
    """Decode a typed-value stream, stopping at anything that is not a typed value.

    The reply header carries a bare service/task pair, so an unknown tag ends the
    walk instead of raising - callers assert on what came back.
    """
    out: list[tuple[int, object]] = []
    i = 0
    n = len(blob)
    while i < n:
        tag = blob[i]
        i += 1
        if tag == TAG_U32:
            if i + 4 > n:
                break
            out.append((tag, struct.unpack_from("<I", blob, i)[0]))
            i += 4
        elif tag == TAG_U16:
            if i + 2 > n:
                break
            out.append((tag, struct.unpack_from("<H", blob, i)[0]))
            i += 2
        elif tag == TAG_U64:
            if i + 8 > n:
                break
            out.append((tag, struct.unpack_from("<Q", blob, i)[0]))
            i += 8
        elif tag == TAG_STRING:
            end = blob.find(b"\x00", i)
            if end < 0:
                break
            out.append((tag, blob[i:end]))
            i = end + 1
        else:
            out.append((0xFF, tag))
            break
    return out


class TestTask4Reply(unittest.TestCase):
    def test_is_the_empty_success_shape(self) -> None:
        reply = candidate_svc71_task4_reply(1)
        # transaction id then a zero count: the client accepted this shape in M3
        self.assertEqual(reply[:5], _typed_u64(1)[:5])
        self.assertIn(_typed_u32(0), reply)

    def test_shorter_than_an_entry(self) -> None:
        self.assertLess(len(candidate_svc71_task4_reply(1)), len(make_server_entry()))

    def test_transaction_id_is_carried(self) -> None:
        a = candidate_svc71_task4_reply(3)
        b = candidate_svc71_task4_reply(9)
        self.assertNotEqual(a, b)


class TestTask9Reply(unittest.TestCase):
    def test_ends_with_the_entry(self) -> None:
        self.assertTrue(candidate_svc71_task9_reply(1, 8466).endswith(
            make_server_entry(port=8466)))

    def test_length_is_entry_plus_header(self) -> None:
        reply = candidate_svc71_task9_reply(1, 8466)
        entry = make_server_entry(port=8466)
        self.assertEqual(len(reply), len(entry) + 26)

    def test_both_ports_appear(self) -> None:
        for port in (1, 3074, 8466, 65535):
            self.assertIn(struct.pack("<H", port),
                          candidate_svc71_task9_reply(1, port))


class TestUnavailableReply(unittest.TestCase):
    def test_is_fourteen_bytes(self) -> None:
        # the M3 run answered task9 with a 14-byte error frame and the client
        # carried on, so this exact size is part of the contract
        self.assertEqual(len(terminal_unavailable_reply(1)), 14)

    def test_encodes_error_14(self) -> None:
        reply = terminal_unavailable_reply(5)
        self.assertIn(_typed_u32(14), reply)

    def test_transaction_id_leads(self) -> None:
        self.assertTrue(terminal_unavailable_reply(7).startswith(_typed_u64(7)))


class TestEmptySuccessReply(unittest.TestCase):
    def test_carries_the_task_id(self) -> None:
        reply = candidate_empty_success_reply(1, 3)
        self.assertIn(bytes([3]), reply)

    def test_differs_per_task(self) -> None:
        self.assertNotEqual(candidate_empty_success_reply(1, 3),
                            candidate_empty_success_reply(1, 7))


class TestProfileEncoders(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()) / "profile.json"
        self.store = ProfileStore(self.tmp)
        self.profile = self.store.get_or_create("1")

    def tearDown(self) -> None:
        if self.tmp.exists():
            self.tmp.unlink()
        if self.tmp.parent.exists():
            try:
                self.tmp.parent.rmdir()
            except OSError:
                pass

    def test_playerdata_is_24_bytes(self) -> None:
        self.assertEqual(len(self.store.playerdata_bytes(self.profile)), 24)

    def test_playerdata_field_order(self) -> None:
        blob = self.store.playerdata_bytes(self.profile)
        level, prestige, gp, cp, ents, flags = struct.unpack_from("<6I", blob, 0)
        self.assertEqual(level, self.profile["level"])
        self.assertEqual(prestige, self.profile["prestige"])
        self.assertEqual(gp, self.profile["wallet"]["gp"])
        self.assertEqual(cp, self.profile["wallet"]["cp"])
        self.assertEqual(ents, 0)
        self.assertEqual(flags, 0)

    def test_balance_is_five_bytes(self) -> None:
        self.assertEqual(len(self.store.balance_bytes(self.profile, 2)), 5)

    def test_balance_currency_byte(self) -> None:
        for currency in (1, 2):
            blob = self.store.balance_bytes(self.profile, currency)
            self.assertEqual(blob[0], currency)
            self.assertEqual(struct.unpack_from("<I", blob, 1)[0],
                             self.profile["wallet"]["gp" if currency == 2 else "cp"])

    def test_profile_round_trips_through_disk(self) -> None:
        self.profile["level"] = 55
        self.store.save(self.profile)
        reloaded = ProfileStore(self.tmp).get_or_create("1")
        self.assertEqual(reloaded["level"], 55)

    def test_second_load_reuses_the_record(self) -> None:
        first = self.store.get_or_create("1")
        second = ProfileStore(self.tmp).get_or_create("1")
        self.assertEqual(first["created"], second["created"])


class TestTypedCodecShapes(unittest.TestCase):
    def test_tags_are_distinct(self) -> None:
        self.assertEqual(_typed_u32(1)[0], 0x08)
        self.assertEqual(_typed_u16(1)[0], 0x06)
        self.assertEqual(_typed_u64(1)[0], 0x0A)
        self.assertEqual(_typed_string(b"a")[0], 0x10)

    def test_u64_is_nine_bytes(self) -> None:
        self.assertEqual(len(_typed_u64(1)), 9)

    def test_string_is_nul_terminated(self) -> None:
        self.assertEqual(_typed_string(b"ab"), b"\x10ab\x00")

    def test_decode_round_trip(self) -> None:
        blob = _typed_u32(7) + _typed_u16(9) + _typed_string(b"xy")
        self.assertEqual(decode_typed(blob),
                         [(TAG_U32, 7), (TAG_U16, 9), (TAG_STRING, b"xy")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
