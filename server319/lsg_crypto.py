"""Build 1649370 raw LSG handshake and authenticated 0x85 frames.

The transcript layout is the 1604220 candidate, qualified here by two
independent 1649370 captures: 0x82 challenge, 0x85 MAC, and AES key/plaintext.
This module has no process-memory dependency and never logs key material.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass

from Crypto.Cipher import AES


class LsgProtocolError(ValueError):
    pass


def _u32(data: bytes, offset: int = 0) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _expand(key: bytes, label: bytes, size: int) -> bytes:
    result = b""
    previous = b""
    counter = 1
    while len(result) < size:
        previous = hmac.digest(key, previous + label + bytes([counter]), "sha1")
        result += previous
        counter += 1
    return result[:size]


@dataclass(frozen=True)
class LsgKeys:
    challenge: bytes
    client_mac: bytes
    server_mac: bytes
    client_aes: bytes
    server_aes: bytes


def derive_keys(hello: bytes, gate: bytes, client_auth: bytes,
                session_key: bytes) -> LsgKeys:
    """Derive only after a complete, consistent 28/26/153-byte handshake.

    The transcript uses a canonical AB81 gate marker even when the observed
    outgoing gate wire marker is 0181. Both observed 1649370 captures require
    this distinction. ``client_auth[:-8]`` excludes the challenge answer.
    """
    if len(session_key) != 24:
        raise LsgProtocolError("session_key_length")
    if (len(hello) != 28 or hello[:8] != bytes.fromhex("c8000000c8000000")
            or hello[8:20] != struct.pack("<III", 210, 220, 0x80000)):
        raise LsgProtocolError("hello_shape")
    if (len(gate) != 26 or _u32(gate) != 22
            or gate[4:6] not in (b"\x01\x81", b"\xab\x81")
            or _u32(gate, 6) not in (210, 220)):
        raise LsgProtocolError("gate_shape")
    if (len(client_auth) != 153 or _u32(client_auth) != 149
            or client_auth[4:6] != b"\xab\x82"):
        raise LsgProtocolError("client_auth_shape")
    canonical_gate = struct.pack("<I", 22) + b"\xab\x81" + gate[6:]
    transcript = hello[8:] + canonical_gate + client_auth[:-8]
    base = hmac.digest(hashlib.sha1(transcript).digest(), session_key, "sha1")
    challenge = _expand(base, b"CLIENTCHAL", 16)
    if not hmac.compare_digest(challenge[:8], client_auth[-8:]):
        raise LsgProtocolError("client_challenge_mismatch")
    material = _expand(base, b"BDDATA", 72)
    return LsgKeys(challenge, material[:20], material[20:40],
                   material[40:56], material[56:72])


def parse_client_frame85(frame: bytes, keys: LsgKeys) -> tuple[int, int, bytes]:
    """Return (counter, inner_type, payload) after MAC/decrypt validation."""
    if (len(frame) < 50 or _u32(frame) != len(frame) - 4
            or frame[4:6] != b"\xab\x85"
            or (len(frame) - 34) % 16):
        raise LsgProtocolError("frame85_shape")
    expected = hmac.digest(keys.client_mac, frame[:-8], "sha1")[:8]
    if not hmac.compare_digest(expected, frame[-8:]):
        raise LsgProtocolError("frame85_mac")
    plaintext = AES.new(keys.client_aes, AES.MODE_CBC, frame[10:26]).decrypt(
        frame[26:-8])
    size = _u32(plaintext)
    # In three captured 1649370 client frames, size covers the inner byte too:
    # 0x54 bytes occupy plaintext[4:88], followed by eight zero pad bytes.
    if size < 1 or size > len(plaintext) - 4 or any(plaintext[4 + size:]):
        raise LsgProtocolError("frame85_plaintext_length_or_padding")
    return _u32(frame, 6), plaintext[4], plaintext[5:4 + size]


def build_server_frame85(keys: LsgKeys, payload: bytes, *, counter: int,
                         iv: bytes, inner_type: int = 1) -> bytes:
    if len(iv) != 16 or not 0 <= counter <= 0xFFFFFFFF or not 0 <= inner_type <= 255:
        raise LsgProtocolError("reply_parameters")
    plaintext = struct.pack("<I", len(payload)) + bytes([inner_type]) + payload
    plaintext += bytes((-len(plaintext)) % 16)
    cipher = AES.new(keys.server_aes, AES.MODE_CBC, iv).encrypt(plaintext)
    body = b"\xab\x85" + struct.pack("<I", counter) + iv + cipher
    frame = struct.pack("<I", len(body) + 8) + body
    return frame + hmac.digest(keys.server_mac, frame, "sha1")[:8]


def build_server_frame85_preamble(keys: LsgKeys, payload: bytes, *, counter: int,
                                  iv: bytes, inner_type: int = 1,
                                  preamble: bytes = bytes(16),
                                  length_covers: str = "body") -> bytes:
    """Server frame whose plaintext is [len][preamble][inner][payload].

    The client's 0xBA3710 message parser reads a 4-byte field and then a
    16-byte field from the plaintext head before the service envelope.  This
    builder exists to A/B that layout; `length_covers` selects whether the
    length prefix counts the preamble (`body`) or only inner+payload.
    """
    if len(preamble) not in (8, 16):
        raise LsgProtocolError("preamble_length")
    if len(iv) != 16 or not 0 <= counter <= 0xFFFFFFFF or not 0 <= inner_type <= 255:
        raise LsgProtocolError("reply_parameters")
    body = bytes([inner_type]) + payload
    declared = len(body) + len(preamble) if length_covers == "body" else len(body)
    plaintext = struct.pack("<I", declared) + preamble + body
    plaintext += bytes((-len(plaintext)) % 16)
    cipher = AES.new(keys.server_aes, AES.MODE_CBC, iv).encrypt(plaintext)
    outer = b"\xab\x85" + struct.pack("<I", counter) + iv + cipher
    frame = struct.pack("<I", len(outer) + 8) + outer
    return frame + hmac.digest(keys.server_mac, frame, "sha1")[:8]
