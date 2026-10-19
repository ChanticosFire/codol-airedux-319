#!/usr/bin/env python
r"""Stage or restore the redirect configuration in the owned 1649370 copy.

This is the "do not cut the network" path: instead of blocking outbound
traffic, point the client's configurable endpoints at loopback and let every
other request be observed. Four files are touched, each with a pre-image:

  dwauth.ini   host/port for LSG and Auth (absent in the shipped 1649370 copy;
               the 1604220 reference uses "127.0.0.1 4174 / 127.0.0.1 4175 /
               03EA"). Layout is a cross-Build candidate, not verified here.
  stun.ini     three STUN hosts (shipped file lists stun*-tub.codol.qq.com)
  iips.ini     IIPS download base URL (shipped value is a Tencent intranet IP)
  cacert.pem   libcurl CA bundle; the project lab CA is appended, never the
               system trust store

Nothing here starts a client, touches the system certificate store or changes
firewall state. `--restore` puts every pre-image back and verifies hashes.

Usage:
  python tools/stage_redirect.py stage  --client-dir runtime\client-1649370 --run-dir runs\<id>
  python tools/stage_redirect.py restore --client-dir runtime\client-1649370 --run-dir runs\<id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGED_ROOT = (REPO_ROOT / "runtime" / "client-1649370").resolve()

OPENSSL_CANDIDATES = [
    Path(r"C:\Program Files\Git\usr\bin\openssl.exe"),
    Path("openssl"),
]

CONFIG_NAMES = ["dwauth.ini", "stun.ini", "iips.ini", "cacert.pem"]

SAN_EXTENSION = """subjectAltName=DNS:localhost,DNS:codol-lobby.local,IP:127.0.0.1
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_openssl() -> str:
    for candidate in OPENSSL_CANDIDATES:
        if str(candidate) == "openssl":
            return "openssl"
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("openssl not found")


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr}")


def make_tls(tls_dir: Path) -> dict:
    tls_dir.mkdir(parents=True, exist_ok=True)
    openssl = find_openssl()
    ca_key = tls_dir / "ca.key"
    ca_crt = tls_dir / "ca.crt"
    server_key = tls_dir / "auth.key"
    server_csr = tls_dir / "auth.csr"
    server_crt = tls_dir / "auth.crt"
    extension = tls_dir / "san.cnf"
    extension.write_text(SAN_EXTENSION, encoding="ascii")
    if not ca_crt.exists():
        run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-keyout", str(ca_key),
             "-out", str(ca_crt), "-days", "3650", "-nodes",
             "-subj", "/CN=CODOL AirRedux Lab CA/O=offline-research"])
    if not server_crt.exists():
        run([openssl, "req", "-newkey", "rsa:2048", "-keyout", str(server_key),
             "-out", str(server_csr), "-nodes",
             "-subj", "/CN=codol-lobby.local/O=offline-research"])
        run([openssl, "x509", "-req", "-in", str(server_csr), "-CA", str(ca_crt),
             "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(server_crt),
             "-days", "3650", "-extfile", str(extension)])
    return {
        "ca_cert": str(ca_crt),
        "server_cert": str(server_crt),
        "server_key": str(server_key),
        "ca_cert_sha256": sha256_file(ca_crt),
        "server_cert_sha256": sha256_file(server_crt),
    }


def stage(client: Path, run_dir: Path, lsg_port: int, auth_port: int, iips_port: int) -> int:
    pre_image = run_dir / "pre-image"
    pre_image.mkdir(parents=True, exist_ok=True)
    tls = make_tls(run_dir / "tls")
    receipt = {
        "build": 1649370,
        "client_dir": str(client),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tls": tls,
        "lsg_port": lsg_port,
        "auth_port": auth_port,
        "iips_port": iips_port,
        "files": {},
        "layout_source": "1604220 launch319 reference; candidate for 1649370",
    }
    ca_pem = Path(tls["ca_cert"]).read_bytes()
    for name in CONFIG_NAMES:
        target = client / name
        backup = pre_image / name
        entry: dict = {"path": str(target)}
        if target.exists():
            if not backup.exists():
                shutil.copy2(target, backup)
            entry["pre_image"] = str(backup)
            entry["pre_sha256"] = sha256_file(backup)
            entry["pre_bytes"] = backup.stat().st_size
        else:
            entry["pre_image"] = None
            entry["pre_sha256"] = None
            entry["pre_bytes"] = None
        receipt["files"][name] = entry

    # dwauth.ini: two "host port" lines (LSG, Auth) plus the title id token.
    (client / "dwauth.ini").write_bytes(
        f"127.0.0.1 {lsg_port}\r\n127.0.0.1 {auth_port}\r\n03EA\r\n".encode("ascii"))
    # stun.ini: one host per line, same shape as the shipped file.
    (client / "stun.ini").write_bytes(b"127.0.0.1\r\n127.0.0.1\r\n127.0.0.1\r\n")
    # iips.ini: keep enable_iips, point the base URL at loopback.
    (client / "iips.ini").write_bytes(
        f'enable_iips=1\r\niips_url="http://127.0.0.1:{iips_port}/"\r\n'.encode("ascii"))
    # cacert.pem: original bundle plus the lab CA (no system store change).
    original_ca = (pre_image / "cacert.pem").read_bytes() if (pre_image / "cacert.pem").exists() else b""
    (client / "cacert.pem").write_bytes(original_ca + b"\n" + ca_pem)

    for name in CONFIG_NAMES:
        target = client / name
        receipt["files"][name]["staged_sha256"] = sha256_file(target)
        receipt["files"][name]["staged_bytes"] = target.stat().st_size
    (run_dir / "stage.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"staged": True, "run_dir": str(run_dir), "files": list(receipt["files"])}, ensure_ascii=False))
    return 0


def restore(client: Path, run_dir: Path) -> int:
    receipt = json.loads((run_dir / "stage.json").read_text(encoding="utf-8"))
    if str(client) != receipt["client_dir"]:
        raise SystemExit("client dir mismatch")
    results = {}
    for name, entry in receipt["files"].items():
        target = client / name
        backup = entry.get("pre_image")
        if backup and Path(backup).exists():
            shutil.copy2(backup, target)
            restored = sha256_file(target)
            results[name] = {"restored": True, "sha256": restored, "matches_pre": restored == entry["pre_sha256"]}
        else:
            if target.exists():
                target.unlink()
            results[name] = {"restored": True, "removed": True}
    (run_dir / "restore.json").write_text(json.dumps({"restored_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                      "files": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"restored": True, "files": results}, ensure_ascii=False))
    return 0 if all(item.get("matches_pre", True) for item in results.values()) else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stage", "restore"])
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--lsg-port", type=int, default=4174)
    parser.add_argument("--auth-port", type=int, default=4175)
    parser.add_argument("--iips-port", type=int, default=8099)
    args = parser.parse_args()
    client = args.client_dir.resolve(strict=True)
    if client != STAGED_ROOT:
        raise SystemExit("refusing: client dir is not the owned staged copy")
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.action == "stage":
        return stage(client, run_dir, args.lsg_port, args.auth_port, args.iips_port)
    return restore(client, run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
