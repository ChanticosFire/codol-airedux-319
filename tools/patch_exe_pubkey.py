"""Swap the publisher RSA public key inside a client exe (trust-root replacement).

    python tools/patch_exe_pubkey.py --exe <path> --pub runs/ff-edit/self.pem.pub
    python tools/patch_exe_pubkey.py --exe <path> --restore

The exe embeds a 270-byte PKCS#1 RSAPublicKey (``30 82 01 0A ...``).  Both the
original client and the offline shell carry the same key at different file
offsets (0x698958 / 0x9AC958), so the offset is scanned unless --offset is given.
A ``.orig-backup`` next to the exe is created on first patch and used by --restore.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

SIZE = 270
MAGIC = b"\x30\x82\x01\x0a"


def find_offset(data: bytes) -> int:
    offset = data.find(MAGIC)
    if offset < 0:
        raise SystemExit("no PKCS#1 RSAPublicKey found")
    return offset


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--pub")
    ap.add_argument("--offset", type=lambda v: int(v, 0))
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    path = Path(args.exe)
    backup = path.with_suffix(path.suffix + ".orig-backup")

    if args.restore:
        if not backup.exists():
            raise SystemExit("no backup to restore")
        shutil.copy2(backup, path)
        print(f"restored {path} from {backup}")
        return 0

    if not args.pub:
        raise SystemExit("--pub required")
    pub = Path(args.pub).read_bytes()
    if len(pub) != SIZE or not pub.startswith(MAGIC):
        raise SystemExit(f"public key must be {SIZE} bytes starting with {MAGIC.hex()}")

    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"backup -> {backup}")
    data = bytearray(path.read_bytes())
    offset = args.offset if args.offset is not None else find_offset(bytes(data))
    current = bytes(data[offset:offset + SIZE])
    if current == pub:
        print(f"already patched at {hex(offset)}")
        return 0
    if not current.startswith(MAGIC):
        raise SystemExit(f"offset {hex(offset)} does not start with the RSA magic")
    data[offset:offset + SIZE] = pub
    path.write_bytes(bytes(data))
    print(f"patched {path} at {hex(offset)}"
          f" old_sha={hashlib.sha256(current).hexdigest()[:16]}"
          f" new_sha={hashlib.sha256(pub).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
