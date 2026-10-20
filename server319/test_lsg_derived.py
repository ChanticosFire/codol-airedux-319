import hashlib
import hmac
import socket
import struct
import threading
import unittest
from types import SimpleNamespace

from Crypto.Cipher import AES

from .lsg_crypto import derive_keys
from .lsg_derived import DerivedLsgServer, _read_frame, _read_exact, terminal_unavailable_reply
from .ticket import SESSION_KEY


class RecordingEvidence:
    def __init__(self):
        self.events = []

    def write(self, name, session, **fields):
        self.events.append((name, fields))


class DerivedServerTests(unittest.TestCase):
    def test_terminal_unavailable_contract_has_no_success_body(self):
        self.assertEqual(terminal_unavailable_reply(2),
                         bytes.fromhex("0a0200000000000000080e000000"))

    def test_synthetic_raw_handshake_and_candidate_reply(self):
        server = DerivedLsgServer.__new__(DerivedLsgServer)
        server.evidence = RecordingEvidence()
        server.token_marker = 0
        server.observed71_empty = True
        server._new_session = lambda: SimpleNamespace(connection_id=1, requests=0)
        peer, accepted = socket.socketpair()
        thread = threading.Thread(target=server._handle, args=(accepted,), daemon=True)
        thread.start()
        try:
            peer.settimeout(3)
            hello = bytes.fromhex("c8000000c8000000d2000000dc00000000000800") + bytes(range(8))
            peer.sendall(hello)
            gate = _read_frame(peer)
            self.assertEqual(gate[4:6], b"\x01\x81")
            prefix = struct.pack("<I", 149) + b"\xab\x82" + bytes(139)
            canonical_gate = gate[:4] + b"\xab\x81" + gate[6:]
            transcript = hello[8:] + canonical_gate + prefix
            base = hmac.digest(hashlib.sha1(transcript).digest(), SESSION_KEY, "sha1")
            challenge = hmac.digest(base, b"CLIENTCHAL\x01", "sha1")[:16]
            client_auth = prefix + challenge[:8]
            peer.sendall(client_auth)
            token = _read_frame(peer)
            self.assertEqual(token, struct.pack("<I", 10) + b"\x00\x83" + challenge[8:])
            keys = derive_keys(hello, gate, client_auth, SESSION_KEY)
            payload = b"\x47\x03\x04"
            plain = struct.pack("<I", len(payload) + 1) + b"\x86" + payload + bytes(8)
            iv = bytes(range(16))
            body = b"\xab\x85" + struct.pack("<I", 1) + iv
            body += AES.new(keys.client_aes, AES.MODE_CBC, iv).encrypt(plain)
            client_frame = struct.pack("<I", len(body) + 8) + body
            client_frame += hmac.digest(keys.client_mac, client_frame, "sha1")[:8]
            peer.sendall(client_frame)
            reply = _read_frame(peer)
            self.assertEqual(reply[4:6], b"\xab\x85")
            self.assertEqual(reply[-8:], hmac.digest(keys.server_mac, reply[:-8], "sha1")[:8])
            out = AES.new(keys.server_aes, AES.MODE_CBC, reply[10:26]).decrypt(reply[26:-8])
            self.assertEqual(out[4], 1)
            self.assertEqual(out[5:14], b"\x0a" + struct.pack("<Q", 1))
            self.assertIn("candidate_task_reply", [name for name, _ in server.evidence.events])
            for counter, task in ((2, 3), (3, 7), (4, 9)):
                payload = bytes((71, 3, task))
                plain = struct.pack("<I", len(payload) + 1) + b"\x86" + payload + bytes(8)
                iv = bytes([counter]) * 16
                body = b"\xab\x85" + struct.pack("<I", counter) + iv
                body += AES.new(keys.client_aes, AES.MODE_CBC, iv).encrypt(plain)
                request = struct.pack("<I", len(body) + 8) + body
                request += hmac.digest(keys.client_mac, request, "sha1")[:8]
                peer.sendall(request)
                reply = _read_frame(peer)
                self.assertEqual(struct.unpack_from("<I", reply, 6)[0], counter)
                self.assertEqual(reply[-8:], hmac.digest(keys.server_mac, reply[:-8], "sha1")[:8])
                result = AES.new(keys.server_aes, AES.MODE_CBC, reply[10:26]).decrypt(reply[26:-8])
                # Default reply for unimplemented tasks is now the 14-byte
                # terminal error (LSG_UNIMPL_MODE / LSG_T9_MODE default to
                # "error14" because that is what the M3 run sent and the client
                # accepted). 21 bytes is the older empty-success shape, still
                # reachable with LSG_UNIMPL_MODE=empty.
                self.assertEqual(result[:4], struct.pack("<I", 14))
                self.assertEqual(result[4], 1)
                self.assertEqual(result[5:14],
                                 b"\x0a" + struct.pack("<Q", counter))
                self.assertEqual(result[14:19], b"\x08" + struct.pack("<I", 14))
            # Four requests are answered in this test: task4 (candidate_task_reply)
            # plus task3, task7 and task9. task3/task7 go through LSG_UNIMPL_MODE
            # (terminal_task_reply by default) and task9 has its own LSG_T9_MODE
            # branch that records candidate_task_reply.
            answered = sum(name in ("candidate_empty_task_reply", "terminal_task_reply",
                                    "candidate_task_reply")
                           for name, _ in server.evidence.events)
            self.assertEqual(answered, 4)
        finally:
            peer.close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
