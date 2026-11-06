"""Boundary checks for the same-build stats upload wire format."""
from __future__ import annotations

import struct
import unittest
import zlib

from .stats164 import CHUNK_SIZE, PROFILE_SIZE, Stats164Upload


class Stats164UploadTests(unittest.TestCase):
    @staticmethod
    def packet(chunk: int, wire_length: int, part: bytes) -> bytes:
        return struct.pack("<BH", chunk, wire_length) + part

    def test_exact_zlib_upload_completes_without_2697_crc(self) -> None:
        profile = bytes(PROFILE_SIZE)
        wire = zlib.compress(profile)
        upload = Stats164Upload()
        result = upload.feed(self.packet(0, len(wire), wire))
        self.assertTrue(result["accepted"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["validation_level"], "wire_only")
        self.assertFalse(result["crc_matches_2697"])
        self.assertEqual(upload.profile, profile)

    def test_invalid_final_zlib_chunk_does_not_commit(self) -> None:
        profile = bytes(PROFILE_SIZE)
        valid = zlib.compress(profile)
        invalid = valid + b"x"
        upload = Stats164Upload()
        bad = upload.feed(self.packet(0, len(invalid), invalid))
        self.assertFalse(bad["accepted"])
        self.assertEqual(bad["reason"], "zlib_size_or_trailing_data")
        self.assertEqual(upload.chunks, {})
        self.assertIsNone(upload.wire_length)
        self.assertIsNone(upload.profile)
        repaired = upload.feed(self.packet(0, len(valid), valid))
        self.assertTrue(repaired["complete"])
        self.assertEqual(upload.profile, profile)

    def test_raw_chunks_require_every_part_and_reject_changed_duplicate(self) -> None:
        profile = bytes(i % 251 for i in range(PROFILE_SIZE))
        upload = Stats164Upload()
        parts = [profile[i:i + CHUNK_SIZE]
                 for i in range(0, PROFILE_SIZE, CHUNK_SIZE)]
        for index, part in enumerate(parts):
            result = upload.feed(self.packet(index, 0, part))
            self.assertTrue(result["accepted"])
            self.assertEqual(result["complete"], index == len(parts) - 1)
        self.assertEqual(upload.profile, profile)
        changed = upload.feed(self.packet(0, 0, b"x" + parts[0][1:]))
        self.assertEqual(changed["reason"], "duplicate_differs")
        self.assertEqual(upload.profile, profile)


if __name__ == "__main__":
    unittest.main()
