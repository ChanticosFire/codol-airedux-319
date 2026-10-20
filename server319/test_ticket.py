"""Independent known vectors and wire-offset checks for local auth tickets."""

import struct
import unittest

from .a22_tiger import tiger
from .ticket import SESSION_KEY, build_ticket


class TigerTests(unittest.TestCase):
    def test_standard_empty_vector(self):
        self.assertEqual(tiger(b"").hex(),
                         "3293ac630c13f0245f92bbb1766e16167a4e58492dde73f3")

    def test_standard_abc_vector(self):
        self.assertEqual(tiger(b"abc").hex(),
                         "2aab1484e8c158f2bfb8c5ff41b57a525129131c957b5f93")


class TicketTests(unittest.TestCase):
    def test_wire_layout_and_checksum(self):
        ticket = build_ticket("934477427295145000", "local", issued_at=1700000000)
        self.assertEqual(len(ticket), 128)
        self.assertEqual(ticket[:5], bytes.fromhex("deadbdef00"))
        self.assertEqual(struct.unpack_from("<I", ticket, 5)[0], 1002)
        self.assertEqual(struct.unpack_from("<II", ticket, 9),
                         (1700000000, 1700003600))
        self.assertEqual(struct.unpack_from("<QQ", ticket, 17),
                         (1002, 934477427295145000))
        self.assertEqual(ticket[33:97], b"local" + bytes(59))
        self.assertEqual(ticket[97:121], SESSION_KEY)
        self.assertEqual(ticket[121:124], b"\x09\x04\x00")
        self.assertEqual(ticket[124:], tiger(ticket[:121])[:4])

    def test_name_is_bounded_without_moving_other_fields(self):
        ticket = build_ticket(username=b"x" * 100, issued_at=1, expires_at=2)
        self.assertEqual(len(ticket), 128)
        self.assertEqual(ticket[33:97], b"x" * 64)
        self.assertEqual(ticket[97:121], SESSION_KEY)

    def test_identity_changes_checksum(self):
        a = build_ticket(1, issued_at=1700000000)
        b = build_ticket(2, issued_at=1700000000)
        self.assertNotEqual(a[124:], b[124:])

    def test_invalid_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            build_ticket(session_key=b"short")
        with self.assertRaises(ValueError):
            build_ticket(issued_at=10, expires_at=10)
        with self.assertRaises(struct.error):
            build_ticket(user_id=-1)


if __name__ == "__main__":
    unittest.main()
