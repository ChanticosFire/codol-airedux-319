"""Re-sign a fastfile with a self-generated RSA key (trust-root replacement).

    python tools/ff_resign.py --source <orig.ff> --output <new.ff> --key <pem>
    python tools/ff_resign.py --make-key <pem>

Why this works: the client stores the *material* private key (1191 byte DER) in
its own exe, so the 40-byte material block (AES-192 key + CTR IV + zone sizes)
can be decrypted.  Only the publisher signature needs a different key, and that
trust root can be swapped in the exe (see tools/patch_exe_pubkey.py).

Layout (IWff0100):
    0x0000  21 B   "IWff0100" + u32(365) + 0x01 + u32(0) + u32(0)
    0x0015  256 B  RSA PKCS#1 v1.5 ciphertext -> 40 B material
    0x0115  8192 B AES-192-CTR header (IV = material[24:40])
    0x2115  ...    hash tables + data blocks
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"E:\GAME\COD\1649370\src")
from Crypto.Cipher import AES  # noqa: E402
from Crypto.Hash import SHA256  # noqa: E402
from Crypto.PublicKey import RSA  # noqa: E402
from Crypto.Signature import pkcs1_15  # noqa: E402
from Crypto.Util import Counter  # noqa: E402
from codol_rebuild.resources import fastfile  # noqa: E402

BLOCK = 8192
HEADER_OFF = 0x115
SIGN_START, SIGN_END = 0x2C, 0x12C
HASH_START, HASH_END = 0x12C, 0x1FD0
SIGNED_LEN = SIGN_END - SIGN_START


def ctr(data: bytes, key: bytes, iv: bytes) -> bytes:
    counter = Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    return AES.new(key, AES.MODE_CTR, counter=counter).encrypt(data)


def make_key(path: str) -> int:
    key = RSA.generate(2048)
    Path(path).write_bytes(key.export_key())
    pub = b"\x30\x82\x01\x0a\x02\x82\x01\x01\x00" + key.n.to_bytes(256, "big") + b"\x02\x03\x01\x00\x01"
    Path(path + ".pub").write_bytes(pub)
    print(f"key={path} pub={path}.pub pub_len={len(pub)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-key")
    ap.add_argument("--source")
    ap.add_argument("--output")
    ap.add_argument("--key")
    ap.add_argument("--exe", default=r"E:\GAME\COD\Original Client\codoMP_client_shipRetail.exe")
    ap.add_argument("--zone-name")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    if args.make_key:
        return make_key(args.make_key)

    raw = bytearray(Path(args.source).read_bytes())
    exe = Path(args.exe).read_bytes()
    prefix = raw[:21]
    if not prefix.startswith(b"IWff0100"):
        raise SystemExit("not an IWff0100 file")
    version = struct.unpack_from("<I", prefix, 8)[0]
    material_key, _, _ = fastfile._load_keys(exe, version, False)
    material = fastfile._decrypt_material(bytes(raw[21:21 + 256]), material_key, version)
    key = material[:24]
    iv = material[24:40]
    header = bytearray(ctr(bytes(raw[HEADER_OFF:HEADER_OFF + BLOCK]), key, iv))
    if header[:8] != b"IWffs100":
        raise SystemExit("header magic mismatch")

    if args.zone_name:
        name = args.zone_name.encode() + b"\0"
        name = name.ljust(HASH_START - 0x12C, b"\0")[: HASH_START - 0x12C]
        header[0x12C:HASH_START] = name
        print("zone name ->", args.zone_name)

    digest = hashlib.sha256(bytes(header[HASH_START:HASH_END])).digest()
    header[0x0C:0x2C] = digest
    sign_key = RSA.import_key(Path(args.key).read_bytes())
    header[SIGN_START:SIGN_END] = pkcs1_15.new(sign_key).sign(SHA256.new(bytes(header[HASH_START:HASH_END])))

    raw[HEADER_OFF:HEADER_OFF + BLOCK] = ctr(bytes(header), key, iv)
    Path(args.output).write_bytes(bytes(raw))
    print(f"wrote {args.output} size={len(raw)} zone={args.zone_name or '-'}")

    if args.verify:
        pub = Path(args.key + ".pub").read_bytes()
        hit = exe.find(b"\x30\x82\x01\x0a")
        print(f"verify hint: first PKCS1 DER at {hex(hit) if hit >= 0 else None}; pub_len={len(pub)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
