#!/usr/bin/env python
"""Local TLS Auth listener for the 1649370 lab.

Listens on 127.0.0.1 and records the TLS handshake (SNI, version, cipher) and
the first HTTP request line/headers. It answers a minimal 200/empty response so
the client's request shape becomes visible without any upstream connection.

The certificate/key come from tools/stage_redirect.py (lab CA + server cert).
Nothing is written back to the client and no client memory is touched.

Usage:
  python tools/lab_auth_server.py --cert runs/<id>/tls/auth.crt \
      --key runs/<id>/tls/auth.key --port 4175 --log runs/<id>/auth.jsonl --seconds 90
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import threading
import time
from pathlib import Path

LOCK = threading.Lock()
LOG_PATH: Path | None = None


def record(entry: dict) -> None:
    entry["utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with LOCK:
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def handle(conn, context: ssl.SSLContext) -> None:
    # After /auth/ the client opens a second connection to the same port that
    # does NOT speak TLS (observed on the 1604220 reference and now here).
    # Peek the first byte: 0x16 (TLS handshake) or 0x80 (SSLv2 hello) means TLS;
    # anything else is the plaintext lobby frame layer.
    try:
        head = conn.recv(16, socket.MSG_PEEK)
    except Exception:
        head = b""
    if head and head[0] not in (0x16, 0x80):
        record({"event": "plaintext_connect", "first_bytes": head[:16].hex()})
        data = b""
        try:
            conn.settimeout(8)
            while len(data) < 65536:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
                record({"event": "plaintext_recv", "bytes": len(chunk), "total": len(data),
                        "hex": chunk[:512].hex()})
                if len(data) >= 8192:
                    break
        except Exception as exc:
            record({"event": "plaintext_error", "error": type(exc).__name__, "detail": str(exc)[:200]})
        finally:
            if data:
                record({"event": "plaintext_summary", "total": len(data), "hex": data[:2048].hex()})
            try:
                conn.close()
            except Exception:
                pass
        return
    try:
        tls = context.wrap_socket(conn, server_side=True)
    except Exception as exc:  # handshake failure is evidence too
        record({"event": "tls_handshake_failed", "error": type(exc).__name__, "detail": str(exc)[:200]})
        conn.close()
        return
    try:
        record({"event": "tls_ok", "version": tls.version(), "cipher": tls.cipher()[0] if tls.cipher() else None,
                "sni": getattr(tls, "server_hostname", None)})
        tls.settimeout(12)
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = tls.recv(65536)
            if not chunk:
                break
            raw += chunk
        head, _, rest = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1", "replace").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ": " in line:
                key, _, value = line.partition(": ")
                headers[key.lower()] = value
        body = rest
        length = int(headers.get("content-length") or 0)
        if headers.get("expect", "").lower() == "100-continue":
            tls.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
        while len(body) < length:
            chunk = tls.recv(65536)
            if not chunk:
                break
            body += chunk
        body = body[:length] if length else body
        record({"event": "http_request", "request_line": lines[0], "headers": lines[1:40],
                "body_len": len(body), "body_hex": body.hex(),
                "body_text": body.decode("utf-8", "replace")[:4000]})
        # 1604220 reference shape, applied as a candidate for 1649370:
        # result 700 + 128-byte tickets + DW-* headers. Ticket bytes are zero
        # until the Tiger/3DES path is verified for this Build.
        import base64
        import json as _json
        request = {}
        try:
            request = _json.loads(body.decode("utf-8", "replace"))
        except Exception:
            pass
        zero_ticket = base64.b64encode(b"\x00" * 128).decode()
        auth_task = request.get("auth_task")
        obj = {
            "result": 0,
            "code": 0,
            "success": True,
            "iv_seed": str(request.get("iv_seed", "0")),
            "server_ticket": zero_ticket,
            "server_ticket_size": 128,
            "lsg_server_ticket": zero_ticket,
            "lsg_server_ticket_size": 128,
            "client_ticket": zero_ticket,
            "client_ticket_size": 128,
            "time_to_live": 3600,
            "licenses": [],
            "license_id": int(request.get("title_id", "1002") or 1002),
            "cd_key": "",
            "ciphertext": "",
            "extra_data": "{}",
            "user_id": str(_json.loads(request.get("extra_data", "{}")).get("user_id", "0"))
            if request.get("extra_data") else "0",
            "identity": request.get("identity", "356c4bc3"),
            "title_id": request.get("title_id", "1002"),
        }
        if auth_task is not None:
            obj["auth_task"] = auth_task
        payload = _json.dumps(obj).encode()
        header_block = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            + b"DW-Server-Ticket: " + zero_ticket.encode() + b"\r\n"
            + b"DW-Server-Ticket-Size: 128\r\n"
            + b"DW-Client-Ticket: " + zero_ticket.encode() + b"\r\n"
            + b"DW-Client-Ticket-Size: 128\r\n"
            + b"DW-Ticket-Seed: " + str(request.get("iv_seed", "0")).encode() + b"\r\n"
            + b"Content-Length: " + str(len(payload)).encode() + b"\r\nConnection: keep-alive\r\n\r\n"
        )
        tls.sendall(header_block + payload)
        record({"event": "http_response", "status": 200, "bytes": len(header_block) + len(payload),
                "body_text": payload.decode("utf-8", "replace")[:2000]})
        # Keep the connection open and record whatever the client sends next:
        # that is where the lobby (LSG) frame layer shows up.
        try:
            tls.settimeout(20)
            for _ in range(8):
                more = tls.recv(65536)
                if not more:
                    break
                record({"event": "post_auth_frame", "bytes": len(more), "hex": more[:2048].hex()})
        except Exception as exc:
            record({"event": "post_auth_idle", "detail": type(exc).__name__})
    except Exception as exc:
        record({"event": "io_error", "error": type(exc).__name__, "detail": str(exc)[:200]})
    finally:
        try:
            tls.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--port", type=int, default=4175)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--ciphers", default="DEFAULT@SECLEVEL=1")
    args = parser.parse_args()
    global LOG_PATH
    LOG_PATH = args.log.resolve()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(args.cert), str(args.key))
    # The 2019-era client ships an old libcurl/OpenSSL: it offers legacy
    # signature algorithms and does not speak TLS 1.3. Pin the server to
    # TLS <= 1.2 and drop the security level so RSA/SHA1 suites are usable.
    try:
        context.set_ciphers(args.ciphers)
    except ssl.SSLError:
        pass
    context.minimum_version = ssl.TLSVersion.TLSv1
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    for flag in ("OP_NO_TLSv1_3",):
        context.options |= getattr(ssl, flag, 0)

    def sni_callback(sock, server_name, _context):
        record({"event": "sni", "server_name": server_name})
        return None

    context.sni_callback = sni_callback

    server = socket.create_server(("127.0.0.1", args.port), reuse_port=False)
    server.settimeout(1)
    deadline = time.time() + args.seconds
    print(f"auth listening 127.0.0.1:{args.port}", flush=True)
    while time.time() < deadline:
        try:
            conn, _addr = server.accept()
        except socket.timeout:
            continue
        thread = threading.Thread(target=handle, args=(conn, context), daemon=True)
        thread.start()
    server.close()
    print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



