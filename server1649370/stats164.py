"""Bounded Build 1649370 public-profile upload assembly.

Port of the wire checks in the community codol_stats.c
CODOL_AcceptClientStats164 path.  This module never writes a profile to disk.
"""
from __future__ import annotations

import struct
import zlib

PROFILE_SIZE = 32768
CHUNK_SIZE = 1238


class Stats164Upload:
    def __init__(self) -> None:
        self.wire_length: int | None = None
        self.chunks: dict[int, bytes] = {}
        self.profile: bytes | None = None

    def feed(self, packet: bytes) -> dict:
        if len(packet) < 3:
            return {"accepted": False, "reason": "truncated_header"}
        chunk = packet[0]
        wire_length = struct.unpack_from("<H", packet, 1)[0]
        if wire_length > PROFILE_SIZE:
            return {"accepted": False, "reason": "wire_length_exceeds_profile"}
        total = wire_length or PROFILE_SIZE
        count = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
        if chunk >= count:
            return {"accepted": False, "reason": "chunk_outside_wire_length"}
        expected = min(CHUNK_SIZE, total - chunk * CHUNK_SIZE)
        if len(packet) - 3 != expected:
            return {"accepted": False, "reason": "chunk_length_mismatch",
                    "chunk": chunk, "expected": expected, "actual": len(packet) - 3}
        if self.wire_length is not None and self.wire_length != wire_length:
            return {"accepted": False, "reason": "wire_length_changed"}
        part = packet[3:]
        old = self.chunks.get(chunk)
        if old is not None and old != part:
            return {"accepted": False, "reason": "duplicate_differs"}
        pending = {**self.chunks, chunk: part}
        missing = ((1 << count) - 1) & ~sum(1 << index for index in pending)
        result = {"accepted": True, "chunk": chunk, "wire_length": wire_length,
                  "received_count": len(pending), "required_count": count,
                  "missing_mask": missing, "complete": self.profile is not None}
        if missing or self.profile is not None:
            self.wire_length = wire_length
            self.chunks[chunk] = part
            return result
        wire = b"".join(pending[index] for index in range(count))
        if wire_length:
            decoder = zlib.decompressobj()
            try:
                profile = decoder.decompress(wire, PROFILE_SIZE + 1)
                if len(profile) <= PROFILE_SIZE:
                    profile += decoder.flush(PROFILE_SIZE + 1 - len(profile))
            except zlib.error:
                return {**result, "accepted": False, "reason": "invalid_zlib"}
            if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or
                    len(profile) != PROFILE_SIZE):
                return {**result, "accepted": False, "reason": "zlib_size_or_trailing_data"}
        else:
            profile = wire
        if len(profile) != PROFILE_SIZE:
            return {**result, "accepted": False, "reason": "profile_size_mismatch"}
        version = struct.unpack_from("<I", profile, 4)[0]
        schema = struct.unpack_from("<I", profile, 8)[0]
        crc = struct.unpack_from("<I", profile)[0]
        # The same-build community receiver accepts the exact wire stream
        # without applying the unrelated 2697 archive CRC.  Completion here
        # means transport assembly only: gameserver logs the metadata but does
        # not bind these bytes to a player or publish a loadout.
        self.wire_length = wire_length
        self.chunks[chunk] = part
        self.profile = profile
        return {**result, "complete": True, "profile_size": len(profile),
                "profile_version": version, "profile_schema": schema,
                "crc_matches_2697": crc == zlib.crc32(profile[4:]) & 0xFFFFFFFF,
                "validation_level": "wire_only"}
