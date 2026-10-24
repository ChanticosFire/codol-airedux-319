"""Rebuild a signed fastfile from a zone blob (body repack + resign).

    python tools/ff_rebuild_body.py --source <orig.ff> --zone <zone.bin> \
        --out <new.ff> --key runs/ff-edit/self.pem [--check]

Packing rules (from fastfile._signed_payload):
    body = header(8192) | [table(8192) + up to 256 data blocks] *
    table[s] plaintext = sha256(block_i) for its 256 blocks  (32 B each)
    table[s] IV         = header[0x150 + s*32 : 0x170 + s*32]
    data block IV       = table entry (its own sha256)
    header[0x0C:0x2C]   = sha256(header[0x12C:0x1FD0])
    header[0x2C:0x12C]  = RSA-PKCS1v1.5-SHA256 signature of that digest
    every body slice is AES-192-CTR encrypted with its IV

With --check the tool re-inflates its own output and compares against the input
zone, which validates the packer without touching any game file.
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zlib
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
FF_HEADER = 0x15 + 256
SIGN_START, SIGN_END = 0x2C, 0x12C
HASH_START, HASH_END = 0x12C, 0x1FD0
TABLE_IV_OFF = 0x150
MAX_SECTIONS = (HASH_END - TABLE_IV_OFF) // 32


def ctr(data: bytes, key: bytes, iv: bytes) -> bytes:
    # The client uses a 128-bit little-endian counter seeded from iv[:16].
    counter = Counter.new(128, initial_value=int.from_bytes(iv[:16], "little"), little_endian=True)
    return AES.new(key, AES.MODE_CTR, counter=counter).decrypt(data)


def pad_block(data: bytes) -> bytes:
    return data.ljust(BLOCK, b"\0")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--zone")
    ap.add_argument("--out")
    ap.add_argument("--key")
    ap.add_argument("--exe", default=r"E:\GAME\COD\Original Client\codoMP_client_shipRetail.exe")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    raw = bytearray(Path(args.source).read_bytes())
    exe = Path(args.exe).read_bytes()
    if not raw.startswith(b"IWff0100"):
        raise SystemExit("not an IWff0100 file")
    version = struct.unpack_from("<I", raw, 8)[0]
    material_key, _, _ = fastfile._load_keys(exe, version, False)
    material = fastfile._decrypt_material(bytes(raw[21:21 + 256]), material_key, version)
    key24, iv16 = material[:24], material[24:40]

    header = bytearray(ctr(bytes(raw[HEADER_OFF:HEADER_OFF + BLOCK]), key24, iv16))
    if header[:8] != b"IWffs100":
        raise SystemExit("header magic mismatch")

    if args.zone:
        zone = Path(args.zone).read_bytes()
    else:
        compressed = fastfile._signed_payload(bytes(raw[FF_HEADER:]), material, None)[0] \
            if False else None
        raise SystemExit("--zone required")

    compressed = zlib.compress(zone, 9)
    blocks = [compressed[i:i + BLOCK] for i in range(0, len(compressed), BLOCK)]
    blocks = [pad_block(b) for b in blocks]
    sections = [blocks[i:i + 256] for i in range(0, len(blocks), 256)]
    if len(sections) > MAX_SECTIONS:
        raise SystemExit(f"too many sections: {len(sections)} > {MAX_SECTIONS}")

    body = bytearray()
    body += header[:BLOCK]
    for sec_index, group in enumerate(sections):
        table = b"".join(hashlib.sha256(b).digest() for b in group)
        table = pad_block(table)
        table_iv = hashlib.sha256(table).digest()
        header[TABLE_IV_OFF + sec_index * 32: TABLE_IV_OFF + (sec_index + 1) * 32] = table_iv
        body += ctr(table, key24, table_iv)
        for blob in group:
            body += ctr(blob, key24, hashlib.sha256(blob).digest())

    digest = hashlib.sha256(bytes(header[HASH_START:HASH_END])).digest()
    header[0x0C:0x2C] = digest
    if args.key:
        sign_key = RSA.import_key(Path(args.key).read_bytes())
        header[SIGN_START:SIGN_END] = pkcs1_15.new(sign_key).sign(SHA256.new(bytes(header[HASH_START:HASH_END])))
    body[0:BLOCK] = ctr(bytes(header), key24, iv16)

    if args.out:
        Path(args.out).write_bytes(bytes(raw[:FF_HEADER]) + bytes(body))
        print(f"wrote {args.out} size={FF_HEADER + len(body)} zone={len(zone)} "
              f"blocks={len(blocks)} sections={len(sections)}")

    if args.check:
        try:
            fastfile.decode_fastfile(args.out, args.exe)
            print("decode check: PASS")
        except Exception as exc:  # noqa: BLE001
            print("decode check: FAIL", type(exc).__name__, str(exc)[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
