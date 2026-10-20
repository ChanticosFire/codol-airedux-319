"""Synthetic plaintext bdAuthTicket for the local 1649370 lab.

Layout follows 他人文件参考/服务端.zip, lib/codol_server/wire.py:144-159.
The fixed session key is public test material, not an upstream credential.
No encryption or server signature is implied by this serializer.
"""

from __future__ import annotations

import struct
import time

from .a22_tiger import tiger

TICKET_MAGIC = 0xEFBDADDE
TITLE_ID = 1002
SESSION_KEY = bytes(range(24))
TICKET_SIZE = 128


def build_ticket(user_id: int | str = 1, username: str | bytes = b"player", *,
                 title_id: int = TITLE_ID, issued_at: int | None = None,
                 expires_at: int | None = None,
                 session_key: bytes = SESSION_KEY,
                 magic: int = TICKET_MAGIC) -> bytes:
    """Serialize 128 bytes with a Tiger1 checksum over bytes 0..120.

    Times are Unix seconds. The default validity period is one hour; explicit
    timestamps make protocol fixtures reproducible. Integer range errors are
    rejected by struct.pack_into rather than silently wrapping identities.
    """
    issued_at = int(time.time()) if issued_at is None else int(issued_at)
    expires_at = issued_at + 3600 if expires_at is None else int(expires_at)
    if expires_at <= issued_at:
        raise ValueError("expires_at must be later than issued_at")
    if len(session_key) != 24:
        raise ValueError("session_key must contain exactly 24 bytes")
    name = username.encode("utf-8") if isinstance(username, str) else bytes(username)
    ticket = bytearray(TICKET_SIZE)
    struct.pack_into("<IBIIIQQ", ticket, 0, magic, 0, title_id,
                     issued_at, expires_at, title_id, int(user_id))
    ticket[33:97] = name[:64].ljust(64, b"\x00")
    ticket[97:121] = session_key
    ticket[121:124] = b"\x09\x04\x00"
    ticket[124:128] = tiger(bytes(ticket[:121]))[:4]
    return bytes(ticket)
