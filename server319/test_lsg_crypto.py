"""Synthetic frame tests; real captured sessions use tools/verify_lsg_capture.py."""

import hashlib
import hmac
import struct
import unittest

from Crypto.Cipher import AES

from .lsg_crypto import (LsgProtocolError, build_server_frame85, derive_keys,
                         parse_client_frame85)
from .ticket import SESSION_KEY


def fixture():
    hello = bytes.fromhex("c8000000c8000000d2000000dc00000000000800") + bytes(range(8))
    gate_body = b"\x01\x81" + struct.pack("<I", 220) + bytes(range(8, 24))
    gate = struct.pack("<I", len(gate_body)) + gate_body
    prefix = struct.pack("<I", 149) + b"\xab\x82" + bytes(139)
    transcript = hello[8:] + struct.pack("<I", 22) + b"\xab\x81" + gate[6:] + prefix
    base = hmac.digest(hashlib.sha1(transcript).digest(), SESSION_KEY, "sha1")
    challenge = hmac.digest(base, b"CLIENTCHAL\x01", "sha1")[:16]
    client_auth = prefix + challenge[:8]
    return hello, gate, client_auth


class LsgCryptoTests(unittest.TestCase):
    def test_challenge_and_signed_client_frame(self):
        hello, gate, client_auth = fixture()
        keys = derive_keys(hello, gate, client_auth, SESSION_KEY)
        self.assertEqual(client_auth[-8:], keys.challenge[:8])
        payload = b"\x47\x03\x04"
        plain = struct.pack("<I", len(payload) + 1) + b"\x86" + payload + bytes(8)
        iv = bytes(range(16))
        body = b"\xab\x85" + struct.pack("<I", 7) + iv
        body += AES.new(keys.client_aes, AES.MODE_CBC, iv).encrypt(plain)
        frame = struct.pack("<I", len(body) + 8) + body
        frame += hmac.digest(keys.client_mac, frame, "sha1")[:8]
        self.assertEqual(parse_client_frame85(frame, keys), (7, 0x86, payload))
        tampered = frame[:-1] + bytes([frame[-1] ^ 1])
        with self.assertRaisesRegex(LsgProtocolError, "frame85_mac"):
            parse_client_frame85(tampered, keys)

    def test_server_reply_has_independently_checkable_mac_and_plaintext(self):
        keys = derive_keys(*fixture(), SESSION_KEY)
        payload = bytes.fromhex("0a0800000000")
        iv = bytes(range(16, 32))
        frame = build_server_frame85(keys, payload, counter=9, iv=iv)
        self.assertEqual(struct.unpack_from("<I", frame)[0], len(frame) - 4)
        self.assertEqual(frame[4:6], b"\xab\x85")
        self.assertEqual(frame[-8:], hmac.digest(keys.server_mac, frame[:-8], "sha1")[:8])
        plain = AES.new(keys.server_aes, AES.MODE_CBC, iv).decrypt(frame[26:-8])
        self.assertEqual(plain[:5 + len(payload)],
                         struct.pack("<I", len(payload)) + b"\x01" + payload)
        self.assertFalse(any(plain[5 + len(payload):]))

    def test_wrong_challenge_rejected_before_keys_are_used(self):
        hello, gate, client_auth = fixture()
        wrong = client_auth[:-1] + bytes([client_auth[-1] ^ 1])
        with self.assertRaisesRegex(LsgProtocolError, "client_challenge_mismatch"):
            derive_keys(hello, gate, wrong, SESSION_KEY)


if __name__ == "__main__":
    unittest.main()
