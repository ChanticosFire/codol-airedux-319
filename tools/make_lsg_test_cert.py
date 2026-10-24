"""Regenerate the LSG test certificate that was lost during the runs/ cleanup.

`server319.lsg --cert --key` only needs a usable PEM pair for the local
TLS listener; the client connects over UDP for the game handshake, so a fresh
self-signed certificate is sufficient and keeps experiments reproducible.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

OUT = Path(r"E:\GAME\COD\codol-airedux\319\runs\20261020-live-derived01\tls")
OUT.mkdir(parents=True, exist_ok=True)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "codol-airedux-319 test"),
])
now = datetime.now(timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(days=1))
    .not_valid_after(now + timedelta(days=3650))
    .add_extension(x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
    ]), critical=False)
    .sign(key, hashes.SHA256())
)

crt_path = OUT / "auth.crt"
key_path = OUT / "auth.key"
crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
key_path.write_bytes(key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
))
print(f"cert: {crt_path}  ({crt_path.stat().st_size} B)")
print(f"key : {key_path}  ({key_path.stat().st_size} B)")
print(f"valid until: {cert.not_valid_after_utc}")
