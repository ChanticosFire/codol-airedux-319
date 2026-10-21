"""Probe the 2697 getchallenge/connect text handshake with the real name encoding.

Usage: python tools/probe_2697_connect.py [--port 28969] [--name player]
"""
from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path


def encode_name(name: str) -> str:
    return name.encode("utf-16-le").hex()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=28969)
    parser.add_argument("--name", default="player")
    parser.add_argument("--out", default="runs/2697-connect-probe.json")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(4)
    target = (args.host, args.port)
    xuid = "a731af49a6a2c7e2"
    result = {"target": f"{args.host}:{args.port}", "xuid": xuid, "name": args.name,
              "name_hex": encode_name(args.name), "steps": []}
    try:
        sock.sendto(b"\xff\xff\xff\xffgetchallenge 0 \"" + xuid.encode() + b"\"", target)
        challenge, _ = sock.recvfrom(2048)
        result["steps"].append({"step": "getchallenge", "response": challenge.hex(),
                                "ascii": challenge.decode("latin-1", "replace")})
        cookie = challenge.split(b"\x00")[0].decode("latin-1").split()[-1]
        info = ("\\name\\%s\\xuid\\%s\\challenge\\%s\\natType\\1\\checksum\\0"
                "\\2490\\1649370\\statver\\1") % (encode_name(args.name), xuid, cookie)
        packet = ("\xff\xff\xff\xffconnect %s \"%s\"" % (xuid, info)).encode("latin-1")
        sock.sendto(packet, target)
        response, _ = sock.recvfrom(4096)
        result["steps"].append({"step": "connect", "request": packet.hex(),
                                "response": response.hex(),
                                "ascii": response.decode("latin-1", "replace")})
        result["ok"] = b"connectResponse" in response
    except Exception as error:  # noqa: BLE001 - report the probe failure
        result["ok"] = False
        result["error"] = repr(error)
    finally:
        sock.close()
    result["time"] = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
