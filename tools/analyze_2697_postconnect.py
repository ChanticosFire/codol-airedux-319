"""Characterize the 2697 packets sent immediately after connect."""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

XUID = "a731af49a6a2c7e2"
NAME_HEX = "player".encode("utf-16-le").hex()
TARGET = ("127.0.0.1", 28969)


def main() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    sock.sendto(b"\xff\xff\xff\xffgetchallenge 0 \"" + XUID.encode() + b"\"", TARGET)
    challenge, _ = sock.recvfrom(2048)
    cookie = challenge.split(b"\x00")[0].decode("latin-1").split()[-1]
    info = ("\\name\\%s\\xuid\\%s\\challenge\\%s\\natType\\1\\checksum\\0"
            "\\2490\\1649370\\statver\\1") % (NAME_HEX, XUID, cookie)
    sock.sendto(("\xff\xff\xff\xffconnect %s \"%s\"" % (XUID, info)).encode("latin-1"), TARGET)
    reply, _ = sock.recvfrom(4096)
    sock.settimeout(2)
    packets = []
    while len(packets) < 600:
        try:
            data, _ = sock.recvfrom(8192)
        except socket.timeout:
            break
        packets.append(data.hex())
    sock.close()
    parsed = []
    for raw in packets:
        data = bytes.fromhex(raw)
        if len(data) == 9:
            seq = int.from_bytes(data[0:4], "little")
            zero = int.from_bytes(data[4:8], "little")
            checksum = data[8]
            parsed.append({"seq": seq, "zero": zero, "checksum": checksum})
    pattern = all(item["zero"] == 0 and item["checksum"] == ((0x67 - item["seq"]) & 0xFF)
                  for item in parsed)
    result = {"challenge": challenge.hex(), "connect_response": reply.hex(),
              "packet_count": len(packets), "nine_byte_count": len(parsed),
              "pattern_checksum_0x67_minus_seq": pattern,
              "first": parsed[:4], "last": parsed[-4:]}
    out = Path("evidence/experiments/20261021-1649370-postconnect-packets.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
