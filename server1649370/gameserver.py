"""Our own CODOL game server for Build 1649370 (protocol generation 1.1.1.13).

Why this exists
===============
The 2697 dedrun we lease is a protocol-compatible *binary* we cannot instrument.
Every question about address matching, sequence windows or ack semantics has so
far cost a full session of blind memory reads.  This server is ours: it logs
every received datagram, every parsed field and every reply, so the client's
behaviour can be read directly instead of inferred.

Protocol scope (verified against the 1649370 client and the 2697 source)
=======================================================================
Out-of-band (OOB) datagrams start with ``0xFFFFFFFF`` and carry a NUL-terminated
command string.  The client uses three of them during startup:

    getchallenge 0 "<token>"     -> challengeResponse <challenge>
    connect <uid> "\\key\\value..." -> connectResponse \\mapname\\...\\shortversion\\1.1.1.13
    stats                        -> statsResponse 0

In-band datagrams are ``seq(4) + body`` (the 2697 target omits qport); the body
is XOR-ciphered with ``challenge ^ (byte)serverId ^ messageAcknowledge`` driven
by ``reliableCommands[reliableAck & 127].command``.  Phase 2 adds that layer;
phase 1 here only answers OOB so the handshake can be observed end to end.

Transport note
==============
The 1649370 client writes its outbound packets into an in-process ring, not to a
socket.  ``tools/ring_bridge_1649370.py forward`` already drains that ring and
speaks UDP, so this server is a plain UDP endpoint that the bridge forwards to.

    python -m server1649370.gameserver --port 28971 --log runs/gs.jsonl
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

PROTOCOL_GENERATION = "1.1.1.13"
DEFAULT_MAP = "mp_cross_fire"
DEFAULT_GAMETYPE = "war"
DEFAULT_MAXCLIENTS = 12


def _load_gamestate_plaintext() -> bytes:
    """Load the fully reassembled 3426-byte gamestate.

    tools/reassemble_2697_gamestate.py documented the fragment layout and we
    reassembled the three captured fragments into runs/gamestate-3426.bin.  That
    file is the exact payload a real server sent for mp_cross_fire.
    """
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "runs" / "gamestate-3426.bin"
    return path.read_bytes() if path.exists() else b""


GAMESTATE_PLAINTEXT = _load_gamestate_plaintext()


@dataclass
class ServerState:
    """Everything we know about peers, kept explicit for logging."""

    started: float = field(default_factory=time.time)
    peers: dict = field(default_factory=dict)
    counters: dict = field(default_factory=lambda: {
        "oob_received": 0, "oob_sent": 0, "inband_received": 0, "inband_sent": 0,
        "getchallenge": 0, "connect": 0, "stats": 0, "unknown": 0,
    })

    def peer(self, addr: tuple) -> dict:
        row = self.peers.get(addr)
        if row is None:
            row = {"first_seen": time.time(), "challenge": None,
                   "userinfo": None, "build": None, "packets": 0}
            self.peers[addr] = row
        row["packets"] += 1
        return row


class GameServer:
    """Minimal, fully logged out-of-band responder."""

    def __init__(self, port: int, log_path: str | None = None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(1.0)
        self.state = ServerState()
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.running = True

    # ------------------------------------------------------------------ logging
    def log(self, event: dict) -> None:
        event = {"ts": round(time.time(), 6), **event}
        line = json.dumps(event, ensure_ascii=False, default=str)
        print(line, flush=True)
        if self.log_path:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    # ------------------------------------------------------------------ sending
    def send_oob(self, addr: tuple, text: str) -> None:
        payload = b"\xff\xff\xff\xff" + text.encode("latin-1", "replace")
        self.sock.sendto(payload, addr)
        self.state.counters["oob_sent"] += 1
        self.log({"dir": "out", "kind": "oob", "to": f"{addr[0]}:{addr[1]}",
                  "text": text, "hex": payload.hex()})

    # ------------------------------------------------------------------ parsing
    @staticmethod
    def split_quoted(text: str) -> list[str]:
        """Split on spaces but keep "..." groups together."""
        out, buf, quoted = [], [], False
        for ch in text:
            if ch == '"':
                quoted = not quoted
                continue
            if ch == " " and not quoted:
                if buf:
                    out.append("".join(buf))
                    buf = []
                continue
            buf.append(ch)
        if buf:
            out.append("".join(buf))
        return out

    @staticmethod
    def parse_userinfo(blob: str) -> dict:
        """Turn ``\\k\\v\\k\\v`` into a dict; count of pairs is not trusted."""
        parts = [p for p in blob.split("\\") if p]
        info = {}
        for i in range(0, len(parts) - 1, 2):
            info[parts[i]] = parts[i + 1]
        return info

    # ------------------------------------------------------------------ handlers
    def on_getchallenge(self, addr: tuple, args: list[str], peer: dict) -> None:
        self.state.counters["getchallenge"] += 1
        token = args[0] if args else ""
        challenge = int(time.time() * 1000) & 0x7FFFFFFF
        peer["challenge"] = challenge
        self.log({"dir": "in", "kind": "getchallenge", "from": f"{addr[0]}:{addr[1]}",
                  "token": token, "challenge_assigned": challenge})
        self.send_oob(addr, f"challengeResponse {challenge}")

    def on_connect(self, addr: tuple, args: list[str], peer: dict) -> None:
        self.state.counters["connect"] += 1
        uid = args[0] if args else ""
        userinfo_text = args[1] if len(args) > 1 else ""
        info = self.parse_userinfo(userinfo_text)
        peer["userinfo"] = info
        peer["build"] = info.get("shortversion") or info.get("2490")
        self.log({"dir": "in", "kind": "connect", "from": f"{addr[0]}:{addr[1]}",
                  "uid": uid, "userinfo_keys": sorted(info),
                  "name": info.get("name"), "xuid": info.get("xuid"),
                  "challenge_field": info.get("challenge"),
                  "build_field": info.get("2490")})
        response = (f"connectResponse \\mapname\\{DEFAULT_MAP}"
                    f"\\gametype\\{DEFAULT_GAMETYPE}"
                    f"\\sv_maxclients\\{DEFAULT_MAXCLIENTS}"
                    f"\\protocol\\1\\shortversion\\{PROTOCOL_GENERATION}")
        self.send_oob(addr, response)

    def on_stats(self, addr: tuple, args: list[str], peer: dict) -> None:
        self.state.counters["stats"] += 1
        challenge = peer.get("challenge") or 0
        self.log({"dir": "in", "kind": "stats", "from": f"{addr[0]}:{addr[1]}",
                  "args": args, "challenge": challenge})
        # Echo the challenge the client was given: a bare 0 does not let the
        # client confirm that it is talking to the server that issued it.
        self.send_oob(addr, f"statsResponse {challenge}")

    # ------------------------------------------------------------------ dispatch
    def handle(self, data: bytes, addr: tuple) -> None:
        peer = self.state.peer(addr)
        if data[:4] == b"\xff\xff\xff\xff":
            self.state.counters["oob_received"] += 1
            raw = data[4:]
            text = raw.split(b"\x00", 1)[0].decode("latin-1", "replace")
            parts = self.split_quoted(text)
            command = parts[0].lower() if parts else ""
            args = parts[1:]
            self.log({"dir": "in", "kind": "oob", "from": f"{addr[0]}:{addr[1]}",
                      "command": command, "args": args, "length": len(data)})
            if command == "getchallenge":
                self.on_getchallenge(addr, args, peer)
            elif command == "connect":
                self.on_connect(addr, args, peer)
            elif command == "stats":
                self.on_stats(addr, args, peer)
            else:
                self.state.counters["unknown"] += 1
                self.log({"dir": "in", "kind": "unknown_oob", "command": command,
                          "text": text[:200]})
            return

        # in-band: seq(4) + serverId(1) + messageAcknowledge(4) + body, per the
        # 2697 SV_PacketEvent source. Log every field so we can tell whether the
        # client ciphers this part (a plaintext serverId/messageAck pair would be
        # small and monotonic; ciphertext would look random).
        self.state.counters["inband_received"] += 1
        if len(data) >= 9:
            seq = struct.unpack_from("<i", data, 0)[0]
            server_id = data[4]
            message_ack = struct.unpack_from("<i", data, 5)[0]
            body = data[9:]
            acked_ours = message_ack == peer.get("last_server_seq", 0) and message_ack > 0
            if acked_ours:
                self.state.counters["client_acked_ours"] = self.state.counters.get("client_acked_ours", 0) + 1
            self.log({"dir": "in", "kind": "inband", "from": f"{addr[0]}:{addr[1]}",
                      "seq": seq, "serverId": server_id, "messageAck": message_ack,
                      "acked_our_seq": acked_ours,
                      "length": len(data), "body_len": len(body),
                      "body_head": body[:48].hex(),
                      "body_nonzero": sum(1 for b in body[:48] if b) > 0})
            # Answer with the same shape the client uses: seq(4) + serverId(1)
            # + messageAck(4) + body.  The high bit is the netchan FRAGMENT_BIT,
            # which marks reliable commands; the bridge (and possibly the client)
            # treat such packets specially, so set it to test acknowledgement.
            self.server_seq = getattr(self, "server_seq", 0) + 1
            peer["last_server_seq"] = self.server_seq
            # Build an outbound packet the client can actually decrypt.
            # CL_Netchan_Decode uses key = challenge ^ outgoingSequence with the
            # server's lastClientCommandString as the rolling term.  Our server
            # keeps that string empty, so the key is constant per packet and we
            # can cipher with a plain XOR.  The body is the gamestate plaintext
            # we recovered from a real 2697 capture (map name and serverinfo
            # included), so this is a byte-exact replay test.
            self.server_seq = getattr(self, "server_seq", 0) + 1
            peer["last_server_seq"] = self.server_seq
            # Emit the reassembled gamestate as the same fragment structure a
            # real server used: seq|FRAGMENT_BIT, index, count-1, stride, chunk,
            # then XOR(data).  The ten-byte fragment header is plaintext; only
            # the data is ciphered (index 0 keeps its first four bytes intact).
            payload = GAMESTATE_PLAINTEXT
            frag_size = 1162
            if payload:
                count = (len(payload) + frag_size - 1) // frag_size
                stride = frag_size
                # All fragments of ONE message share a single sequence; the
                # reference capture used seq=3 for index 0,1,2 alike.  Only the
                # next message gets the next sequence.
                # We read the client's incomingSequence at connection+0x34 and it
                # was 1, so the client expects the NEXT server sequence to be 2.
                # Start there instead of at 3.
                self.server_seq = getattr(self, "server_seq", 1) + 1
                seq_word = (self.server_seq | 0x80000000) & 0xFFFFFFFF
                key = ((peer.get("challenge") or 0) ^ (seq_word & 0x7FFFFFFF)) & 0xFF
                for index in range(count):
                    chunk = payload[index * frag_size:(index + 1) * frag_size]
                    data = bytearray(chunk)
                    if index == 0:
                        for i in range(4, len(data)):
                            data[i] ^= key
                    else:
                        for i in range(len(data)):
                            data[i] ^= key
                    header = (struct.pack("<I", seq_word) + bytes([index & 0xFF])
                              + bytes([(count - 1) & 0xFF])
                              + struct.pack("<H", stride)
                              + struct.pack("<H", len(chunk)))
                    packet = header + bytes(data)
                    self.sock.sendto(packet, addr)
                    self.state.counters["inband_sent"] += 1
                    self.log({"dir": "out", "kind": "fragment", "to": f"{addr[0]}:{addr[1]}",
                              "seq": seq_word & 0x7FFFFFFF, "index": index,
                              "count": count, "stride": stride, "chunk": len(chunk),
                              "length": len(packet)})
            key = (peer.get("challenge") or 0) ^ self.server_seq
            cipher = bytes(b ^ ((key >> 0) & 0xFF) for b in plain)
            packet = struct.pack("<I", self.server_seq) + cipher
            self.sock.sendto(packet, addr)
            self.state.counters["inband_sent"] += 1
            self.log({"dir": "out", "kind": "inband", "to": f"{addr[0]}:{addr[1]}",
                      "seq": self.server_seq, "key": key & 0xFF,
                      "plain_len": len(plain), "length": len(packet),
                      "plain_head": plain[:24].hex()})
        else:
            self.log({"dir": "in", "kind": "inband_short", "from": f"{addr[0]}:{addr[1]}",
                      "length": len(data), "hex": data[:64].hex()})

    # ------------------------------------------------------------------ serving
    def serve(self) -> None:
        self.log({"dir": "meta", "kind": "start", "port": self.sock.getsockname()[1],
                  "generation": PROTOCOL_GENERATION, "map": DEFAULT_MAP})
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle(data, addr)
        self.log({"dir": "meta", "kind": "stop", "counters": self.state.counters})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=28971)
    parser.add_argument("--log", default="runs/gs.jsonl")
    args = parser.parse_args()
    server = GameServer(args.port, args.log)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
