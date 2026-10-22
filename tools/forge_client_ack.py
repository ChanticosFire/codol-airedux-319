"""Forge a netchan packet for the 2697 dedrun client to deliver a reliable ACK.

The 1649370 client stops at phase 8 without sending `clc_move`, so the server
keeps `reliableAcknowledge = 0` and never enters CS_ACTIVE.  This tool reads the
client's `client_t` from the dedrun process and encodes a packet the same way
`SV_Netchan_Decode` expects:

    key = challenge ^ (byte)serverId ^ messageAcknowledge
    string = reliableCommands[reliableAcknowledge & 255].command
    for i: if string[index] == 0: index = 0
            key ^= string[index] << (i & 1)
            data[i] ^= key

The plain body is `u32 acknowledgement` + `clc_move` + cmdCount.  The first four
bytes of the packet are the plain netchan sequence.

    python tools/forge_client_ack.py --ack 3 --seq 1 --send
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import socket
import struct
from ctypes import wintypes as W

import read_dedrun_client as client_reader

OFF_RELIABLE_SEQUENCE = client_reader.OFF_RELIABLE_SEQUENCE
OFF_RELIABLE_ACK = client_reader.OFF_RELIABLE_ACK
OFF_RELIABLE_SENT = client_reader.OFF_RELIABLE_SENT
OFF_MESSAGE_ACK = OFF_RELIABLE_SEQUENCE + 12
OFF_GAMESTATE = OFF_RELIABLE_SEQUENCE + 16
OFF_CHALLENGE = OFF_RELIABLE_SEQUENCE + 20
OFF_COMMANDS = 1228


def encode(plain: bytes, challenge: int, server_id: int, message_ack: int, command: bytes) -> bytes:
    key = (challenge ^ (server_id & 0xFF) ^ message_ack) & 0xFF
    data = bytearray(plain)
    index = 0
    for i in range(len(data)):
        if index >= len(command) or command[index] == 0:
            index = 0
        if not command:
            key ^= 0
        else:
            key ^= (command[index] << (i & 1)) & 0xFF
        data[i] ^= key & 0xFF
        index += 1
    return bytes(data)


def find_qport(handle, name_address: int) -> tuple[int, int, int]:
    """Locate netchan.remoteAddress before `name` and read the following qport.

    netchan_t is at client_t+13 (pack(1)); remoteAddress is +0x10 inside it and
    qport +0x20, so qport sits 16 bytes after the 16-byte netadr_t.
    """
    block = client_reader.read(handle, max(0, name_address - 0x1000), 0x1000)
    if not block:
        return 0, 0, 0
    pattern = b"\x02\x00\x00\x00\x7f\x00\x00\x01"
    offset = 0
    while True:
        pos = block.find(pattern, offset)
        if pos < 0:
            break
        port = struct.unpack_from("<H", block, pos + 8)[0]
        qport = struct.unpack_from("<H", block, pos + 16)[0]
        if 0 < port <= 65535 and 0 < qport <= 65535:
            return qport, port, name_address - 0x1000 + pos
        offset = pos + 1
    return 0, 0, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ack", type=int, help="acknowledgement value (default: reliableSequence)")
    parser.add_argument("--seq", type=int, default=1)
    parser.add_argument("--server-id", type=int, default=0)
    parser.add_argument("--target", default="127.0.0.1:28970")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--out", default="runs/forge-ack.json")
    args = parser.parse_args()
    pid = client_reader.find_pid()
    if not pid:
        raise SystemExit("dedrun process not found")
    handle = client_reader.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit("OpenProcess failed")
    result: dict = {"pid": pid}
    try:
        hits = client_reader.find_name(handle, b"AdministraClient\0")
        if not hits:
            raise SystemExit("client name not found")
        base = hits[0]
        raw = client_reader.read(handle, base + OFF_RELIABLE_SEQUENCE, 24)
        values = struct.unpack("<6i", raw)
        challenge = struct.unpack("<i", client_reader.read(handle, base + OFF_CHALLENGE, 4))[0]
        command = client_reader.read(handle, base + OFF_COMMANDS, 64).split(b"\0")[0]
        ack = args.ack if args.ack is not None else values[0]
        qport, client_port, adr_address = find_qport(handle, base)
        result.update({
            "name_address": hex(base), "reliableSequence": values[0],
            "reliableAcknowledge": values[1], "reliableSent": values[2],
            "messageAcknowledge": values[3], "gamestateMessageNum": values[4],
            "challenge": challenge, "command": command.decode("latin-1", "replace"),
            "ack": ack, "seq": args.seq, "server_id": args.server_id,
            "qport": qport, "client_port": client_port, "adr_address": hex(adr_address),
        })
        plain = struct.pack("<I", ack) + b"\x00" + b"\x00"
        body = encode(plain, challenge, args.server_id, values[3], command)
        packet = struct.pack("<IH", args.seq, qport) + body
        result["plain_hex"] = plain.hex()
        result["packet_hex"] = packet.hex()
        if args.send:
            host, port = args.target.split(":")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(packet, (host, int(port)))
            sock.close()
            result["sent"] = True
        after = client_reader.read(handle, base + OFF_RELIABLE_SEQUENCE, 8)
        if after:
            result["after_reliableSequence"], result["after_reliableAcknowledge"] = struct.unpack("<2i", after)
    finally:
        client_reader.k32.CloseHandle(handle)
    import pathlib
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
