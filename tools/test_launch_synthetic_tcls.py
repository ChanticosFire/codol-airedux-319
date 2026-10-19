"""Synthetic tests for tools/launch_synthetic_tcls.py.

No client is launched. The tests cover byte-order helpers, the TCP table
reader, the candidate TCLS mapping layout and the staged-copy guard.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import launch_synthetic_tcls as launcher  # noqa: E402


class ByteOrderTests(unittest.TestCase):
    def test_socket_ip(self):
        self.assertEqual(launcher.socket_ip(0x0100007F), "127.0.0.1")
        self.assertEqual(launcher.socket_ip(0x08080808), "8.8.8.8")
        self.assertEqual(launcher.socket_ip(0), "0.0.0.0")

    def test_socket_port(self):
        # dwLocalPort stores the network-order port in the low 16 bits.
        self.assertEqual(launcher.socket_port(0xD21E), 7890)  # 7890 = 0x1ED2
        self.assertEqual(launcher.socket_port(0x901F), 8080)  # 8080 = 0x1F90


class TcpTableTests(unittest.TestCase):
    def test_rows_are_well_formed(self):
        rows = launcher.tcp_rows()
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIsInstance(row["pid"], int)
            self.assertIn(":", row["local"])
            self.assertIn(":", row["remote"])
            self.assertIsInstance(row["state"], int)


class MappingLayoutTests(unittest.TestCase):
    def test_mapping_written_and_readable(self):
        events = []
        handle, record = launcher.write_mapping(999999999, events)
        self.assertIsNotNone(handle, record)
        try:
            self.assertEqual(record["name"], "TCLS_SHAREDMEMEMORY999999999")
            self.assertEqual(record["record_offset"], 0x14)
            self.assertEqual(record["marker_length"], 30)
            self.assertEqual(record["marker_sha256"],
                             launcher.hashlib.sha256(launcher.SYNTHETIC_MARKER).hexdigest())
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
            k32.OpenFileMappingW.restype = ctypes.c_void_p
            k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                          ctypes.c_uint32, ctypes.c_size_t]
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            opening = k32.OpenFileMappingW(0x000F001F, 0, record["name"])
            self.assertTrue(opening, "mapping should be openable by name")
            view = k32.MapViewOfFile(opening, 0x000F001F, 0, 0, 0xC8)
            self.assertTrue(view)
            try:
                raw = ctypes.string_at(view, 0xC8)
                offset_field = struct.unpack_from("<I", raw, 0x10)[0]
                length_field = struct.unpack_from("<I", raw, 0x14)[0]
                marker = raw[0x18:0x18 + length_field]
                self.assertEqual(offset_field, 0x14)
                self.assertEqual(length_field, 30)
                self.assertEqual(marker, launcher.SYNTHETIC_MARKER)
            finally:
                k32.UnmapViewOfFile(view)
                k32.CloseHandle(opening)
        finally:
            launcher.k32.CloseHandle(handle)


class GuardTests(unittest.TestCase):
    def test_anchors_are_the_pinned_build(self):
        self.assertEqual(launcher.BUILD, 1649370)
        self.assertEqual(set(launcher.ANCHORS), {
            "codoMP_client_shipRetail.exe",
            "codoMP_client_shipRetailBase.dll",
            "IIPS/iips.dll",
            "IIPS/IFS2.dll",
        })

    def test_marker_is_thirty_bytes(self):
        self.assertEqual(len(launcher.SYNTHETIC_MARKER), launcher.MARKER_LENGTH)


if __name__ == "__main__":
    unittest.main()
