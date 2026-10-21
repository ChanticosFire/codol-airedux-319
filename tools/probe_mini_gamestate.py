"""Probe the private mini server's stats + gamestate fragment path."""
from __future__ import annotations

import socket

OOB = b"\xff\xff\xff\xff"
XUID = "a731af49a6a2c7e2"
TARGET = ("127.0.0.1", 28969)


def main() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    sock.sendto(OOB + b'getchallenge 0 "' + XUID.encode() + b'"', TARGET)
    challenge, _ = sock.recvfrom(2048)
    cookie = challenge.split()[-1].decode()
    info = ("\\name\\70006c006100790065007200\\xuid\\" + XUID +
            "\\challenge\\" + cookie + "\\natType\\1")
    sock.sendto(OOB + b"connect " + XUID.encode() + b' "' + info.encode() + b'"', TARGET)
    connect, _ = sock.recvfrom(2048)
    print("connect:", connect[:120])
    for index in range(3):
        packet = OOB + b"stats\x00" + bytes([index]) + b"\x00\x00" + b"x" * 10
        sock.sendto(packet, TARGET)
        print("stats reply:", sock.recvfrom(2048)[0][:40])
    sock.sendto(b"\x01\x00\x00\x00", TARGET)
    lengths = []
    for _ in range(3):
        data, _ = sock.recvfrom(4096)
        lengths.append(len(data))
    print("gamestate lengths:", lengths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
