"""Local synthetic TCP smoke test for the Build 1649370 derived LSG CLI.

Usage: python tools/smoke_lsg_derived.py --run-dir runs/<new-run-id>
No game process, external connection, or host network setting is involved.
"""
import argparse
import hashlib
import hmac
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from Crypto.Cipher import AES

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server319.lsg_crypto import derive_keys
from server319.ticket import SESSION_KEY

PORT = 4174


def read_exact(conn, count):
    data = b""
    while len(data) < count:
        part = conn.recv(count - len(data))
        if not part:
            raise EOFError("peer_closed")
        data += part
    return data


def read_frame(conn):
    size = read_exact(conn, 4)
    return size + read_exact(conn, struct.unpack("<I", size)[0])


def run_client():
    with socket.create_connection(("127.0.0.1", PORT), timeout=2) as conn:
        conn.settimeout(3)
        hello = bytes.fromhex("c8000000c8000000d2000000dc00000000000800") + bytes(range(8))
        conn.sendall(hello)
        gate = read_frame(conn)
        prefix = struct.pack("<I", 149) + b"\xab\x82" + bytes(139)
        transcript = hello[8:] + gate[:4] + b"\xab\x81" + gate[6:] + prefix
        base = hmac.digest(hashlib.sha1(transcript).digest(), SESSION_KEY, "sha1")
        challenge = hmac.digest(base, b"CLIENTCHAL\x01", "sha1")[:16]
        auth = prefix + challenge[:8]
        conn.sendall(auth)
        token = read_frame(conn)
        keys = derive_keys(hello, gate, auth, SESSION_KEY)
        token_ok = token[6:14] == keys.challenge[8:]
        payload = b"\x47\x03\x04"
        plain = struct.pack("<I", len(payload) + 1) + b"\x86" + payload + bytes(8)
        iv = bytes(range(16))
        body = b"\xab\x85" + struct.pack("<I", 1) + iv
        body += AES.new(keys.client_aes, AES.MODE_CBC, iv).encrypt(plain)
        frame = struct.pack("<I", len(body) + 8) + body
        frame += hmac.digest(keys.client_mac, frame, "sha1")[:8]
        conn.sendall(frame)
        reply = read_frame(conn)
        mac_ok = reply[-8:] == hmac.digest(keys.server_mac, reply[:-8], "sha1")[:8]
        decoded = AES.new(keys.server_aes, AES.MODE_CBC, reply[10:26]).decrypt(reply[26:-8])
        return {"gate_length": len(gate), "token_length": len(token),
                "client_frame_length": len(frame), "reply_length": len(reply),
                "token_ok": token_ok, "reply_mac_ok": mac_ok,
                "reply_inner_type": decoded[4],
                "reply_svc71_task4_candidate": decoded[5:14] == b"\x0a" + struct.pack("<Q", 1)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--cert", type=Path,
                        default=ROOT / "runs/20261020-session03/tls/auth.crt")
    parser.add_argument("--key", type=Path,
                        default=ROOT / "runs/20261020-session03/tls/auth.key")
    args = parser.parse_args()
    run = args.run_dir.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()) or run.exists():
        parser.error("run directory must be a new child of workspace runs/")
    run.mkdir(parents=True)
    command = [sys.executable, "-m", "server319.lsg", "--cert", str(args.cert),
               "--key", str(args.key), "--port", str(PORT), "--seconds", "7",
               "--log", str(run / "lsg.jsonl")]
    with (run / "server.stdout.txt").open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=ROOT, stdout=output,
                                   stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("server_exited_before_connect")
                try:
                    result = run_client()
                    break
                except ConnectionRefusedError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("listener_unavailable")
            process.wait(timeout=10)
            result.update({"server_exit": process.returncode,
                           "server_pid": process.pid, "synthetic_only": True})
            (run / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result))
            return 0 if (result["token_ok"] and result["reply_mac_ok"]
                         and result["reply_svc71_task4_candidate"]
                         and result["server_exit"] == 0) else 1
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
