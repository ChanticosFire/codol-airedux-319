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
    stats                        -> statResponse <challenge>

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
import ctypes
import json
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from .native_gamestate import DEFAULT_CONFIGSTRINGS, build_native_gamestate
from .wire164 import build_snapshot, _word

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


class ClientOriginReader:
    """Read the client's predicted origin straight out of its process.

    A static snapshot pins the player: the client predicts forward, then the
    next snapshot snaps it back.  The server therefore mirrors the client's own
    predicted origin into each snapshot (confirmed by ``--follow-client-pid``),
    which is what makes held movement accumulate instead of oscillating.
    """

    CL_PTR = 0x76638F4
    CL_XOR = 0x6891D1C7
    # ps = cl + 0x0C (verified by the 8-byte signature 00 00 a0 3e 78 56 34 12),
    # and playerState_t.origin sits at ps+0x30, so the origin is at cl+0x3C.
    # The previous value 0x3C80 pointed outside playerState and made the
    # mirrored origin garbage.
    PS_ORIGIN = 0x3C
    NET_STATE = 0x76446B0
    SLOTS = ((0x0F, 0), (0x14, 2), (0x18, 1))  # snapshot offset, origin component

    PROCESS_NAME = "codol1649370-offline.exe"

    def __init__(self, pid: int):
        self.pid = pid
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.OpenProcess.restype = ctypes.c_void_p
        self.k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.handle = None
        self.failures = 0
        self._last_attempt = 0.0
        self._ensure_handle()

    def _discover_pid(self):
        """Find the game client by name, so the server need not know its PID.

        Starting the server *before* the client is the order that reliably
        reaches CA_ACTIVE (r576 kept net=10 while the client-first order in
        r575 dropped back to the lobby within 12 s), so the PID cannot be a
        constructor argument in the normal flow.
        """
        k32 = self.k32
        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                        ("th32ProcessID", ctypes.c_uint32),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                        ("th32ParentProcessID", ctypes.c_uint32),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32),
                        ("szExeFile", ctypes.c_char * 260)]
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        k32.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
        k32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        if not snap:
            return None
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        found = None
        try:
            if k32.Process32First(snap, ctypes.byref(entry)):
                while True:
                    if entry.szExeFile.decode("latin-1", "replace").lower() == self.PROCESS_NAME:
                        found = int(entry.th32ProcessID)
                        break
                    if not k32.Process32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            k32.CloseHandle(snap)
        return found

    def _ensure_handle(self, force: bool = False) -> bool:
        if self.handle:
            return True
        # Discovery walks the process list, which is far too slow to run once
        # per _u32() call: before the client exists that stalls the whole UDP
        # loop and the client times out (r577 never got past net=0).  Retry at
        # most once a second.
        now = time.monotonic()
        if not force and now - self._last_attempt < 1.0:
            return False
        self._last_attempt = now
        pid = self.pid
        if not pid or pid < 0:
            pid = self._discover_pid()
            if not pid:
                return False
            self.pid = pid
        self.handle = self.k32.OpenProcess(0x438, False, pid)
        return bool(self.handle)

    def _u32(self, addr: int):
        buf = ctypes.create_string_buffer(4)
        got = ctypes.c_size_t()
        if not self._ensure_handle():
            return None
        ok = self.k32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got))
        if not ok or got.value != 4:
            return None
        return struct.unpack("<I", buf.raw)[0]

    def is_active(self) -> bool:
        return self._u32(self.NET_STATE) == 10

    # keys[] lives in the engine's .data at 0x7508CBC, 12 bytes per key and
    # 0xD28 bytes per client; entry +0x00 and +0x04 both go 0 -> 1 while a key
    # is held (verified live: keys[0x77] = [1,1,33] during W, [0,0,33] idle).
    KEYS_BASE = 0x7508CBC
    KEYS_CLIENT_STEP = 0xD28
    KEYS_ENTRY = 12

    def key_active(self, key: int, client: int = 0) -> bool:
        address = self.KEYS_BASE + client * self.KEYS_CLIENT_STEP + key * self.KEYS_ENTRY
        value = self._u32(address)
        return bool(value)

    def cmd_number(self):
        """The client's current outgoing command number (cl + 0x3B94)."""
        enc = self._u32(self.CL_PTR)
        if not enc:
            return None
        return self._u32((enc ^ self.CL_XOR) + 0x3B94)

    def origin(self):
        if self._u32(self.NET_STATE) != 10:
            return None
        enc = self._u32(self.CL_PTR)
        if not enc:
            return None
        cl = enc ^ self.CL_XOR
        values = []
        for index in range(3):
            word = self._u32(cl + self.PS_ORIGIN + index * 4)
            if word is None:
                return None
            values.append(struct.unpack("<f", struct.pack("<I", word))[0])
        # A half-initialised clientActive_t reads as all zeros; mirroring that
        # would teleport the player to the world origin and crash the client.
        if any(value != value or abs(value) > 1.0e6 for value in values):
            return None
        if all(abs(value) < 1.0e-6 for value in values):
            return None
        return values

    def apply(self, payload: bytes) -> bytes:
        values = self.origin()
        if values is None or len(payload) < 0x1C:
            self.failures += 1
            return payload
        result = bytearray(payload)
        for offset, component in self.SLOTS:
            struct.pack_into("<f", result, offset, values[component])
        return bytes(result)


class RebuildFollower:
    """Encode a fresh snapshot from the client's own predicted origin.

    ``ClientOriginReader.apply`` patched bytes inside an already encoded frame.
    The playerState section is bit packed, so the origin float is not byte
    aligned and the patch desynchronised every following field; the client died
    with ``unhandled_exception`` about 1.5 s after reaching ``net=10``.
    Re-encoding keeps each field on its own bit boundary, and the client has
    been shown to follow a server supplied origin exactly (111.5 -> 301.5).
    """

    def __init__(self, pid: int, speed: float = 190.0):
        self.reader = ClientOriginReader(pid)
        self.counter = 0
        self.last_origin = None
        self.speed = speed
        self.pos = None

    KEY_W = 0x77
    KEY_S = 0x73
    KEY_A = 0x61
    KEY_D = 0x64

    def frame(self, server_time: int | None = None, dt: float = 0.1) -> bytes | None:
        if self.pos is None:
            origin = self.reader.origin()
            if origin is None:
                return None
            self.pos = list(origin)
        elif not self.reader.is_active():
            # Client left the match: stop emitting dynamic frames rather than
            # repeating a stale position (that produced garbage like 0000e013).
            return None
        # The client's own prediction never advances in this build, so the
        # held key drives the position here: this is server-authoritative
        # movement whose *input* is still the player's real key state.
        step = self.speed * dt
        if self.reader.key_active(self.KEY_W):
            self.pos[0] -= step
        if self.reader.key_active(self.KEY_S):
            self.pos[0] += step
        if self.reader.key_active(self.KEY_A):
            self.pos[1] += step
        if self.reader.key_active(self.KEY_D):
            self.pos[1] -= step
        origin = tuple(self.pos)
        self.last_origin = [round(v, 3) for v in origin]
        self.counter += 1
        stamp = server_time if server_time is not None else 72192 + self.counter * 100
        values = {
            0x00: stamp, 0x04: 0, 0x2C: 0, 0xA4: 800, 0xB0: 190, 0xC0: 1023,
            0x158: 0, 0x16C: 60, 0x15C: 1023, 0x170: _word(0.3125),
            # Same distinctive 32-bit marker r546-markers.bin carries; without it
            # the frame is 68 bytes instead of 73 and the client rejects it.
            0x174: 0x12345678,
            # weapon id: the demo gamestate reports alias/recipe counts of 0, so
            # every non-zero id was rejected historically.  Retry now that the
            # client runs a real playerState and a stable session.
            0x4C: 1,
            0x30: _word(origin[0]), 0x34: _word(origin[1]), 0x38: _word(origin[2]),
        }
        # position_base must stay (0,0,0): it is the delta codec's reference for
        # _position(), and passing the live origin produced a frame that differed
        # from the known-good r546-markers.bin in its last two bytes -- the client
        # answered that by dropping back to the lobby within seconds.  With the
        # default base the encoded frame is byte-identical to r546 whenever the
        # origin is unchanged.
        return build_snapshot(values, server_time=stamp,
                              entities=[(0, 1, {2: _word(200.0)})])


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

    def __init__(self, port: int, log_path: str | None = None, delay_send: float = 0.0,
                 checksum_feed: int | None = None, gamestate_source: str = "native",
                 registration_checksum: int = 0xFFB56D7E,
                 challenge_override: int | None = None,
                 snapshot_path: str | None = None, snapshot_delay: float = 3.0,
                 snapshot_seq: int = 5, snapshot_repeat: int = 0,
                 snapshot_interval: float = 0.5,
                 command_path: str | None = None, command_delay: float = 2.0,
                 command_seq: int = 4, configstring_file: str | None = None,
                 command_repeat: int = 1, command_interval: float = 5.0,
                 gamestate_repeat: int = 0, gamestate_interval: float = 20.0,
                 gamestate_map: str | None = None,
                 gamestate_gametype: str | None = None,
                 oob_command: str | None = None, oob_delay: float = 30.0,
                 gamestate_file: str | None = None,
                 connect_extra: str | None = None,
                 snapshot_preserve_time: bool = False,
                 follow_client_pid: int | None = None,
                 client_state_pid: int | None = None,
                 server_command_every: int = 0,
                 server_command_seq: int = 0,
                 server_command_text: str | None = None,
                 snapshot_dir: str | None = None,
                 snapshot_frame_repeat: int = 1,
                 rebuild_follow_pid: int | None = None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.1)
        self.state = ServerState()
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.running = True
        self.delay_send = delay_send
        self.checksum_feed = checksum_feed
        self.gamestate_source = gamestate_source
        self.gamestate_file = Path(gamestate_file) if gamestate_file else None
        self.connect_extra = connect_extra
        self.snapshot_preserve_time = snapshot_preserve_time
        self.gamestate_repeat = int(gamestate_repeat or 0)
        self.gamestate_interval = float(gamestate_interval or 0.0)
        self.gamestate_maps = [(part.strip() or "mp_cross_fire").encode("ascii")
                               for part in (gamestate_map or "mp_cross_fire").split(",")]
        self.gamestate_map = self.gamestate_maps[0]
        self.map_name = self.gamestate_map.decode("ascii")
        self.gamestate_gametype = (gamestate_gametype or DEFAULT_GAMETYPE).encode("ascii")
        self.oob_command = oob_command
        self.oob_delay = float(oob_delay or 0.0)
        self.registration_checksum = registration_checksum
        self.challenge_override = challenge_override
        self.snapshot_path = Path(snapshot_path) if snapshot_path else None
        self.snapshot_files = ([Path(part.strip()) for part in snapshot_path.split(",") if part.strip()]
                               if snapshot_path else [])
        # A directory of frames plays as one continuous stream: every frame is
        # repeated ``snapshot_frame_repeat`` times so the client keeps receiving
        # snapshots while it steps through candidate values.  Sparse frames
        # (one send per candidate) leave the client stuck in CA_CHALLENGING.
        if snapshot_dir:
            directory = Path(snapshot_dir)
            if not directory.is_dir():
                raise ValueError(f"snapshot directory does not exist: {directory}")
            frames = sorted(directory.glob("*.bin"))
            if not frames:
                raise ValueError(f"snapshot directory has no *.bin frames: {directory}")
            repeat = max(1, int(snapshot_frame_repeat or 1))
            expanded: list[Path] = []
            for frame in frames:
                expanded.extend([frame] * repeat)
            self.snapshot_files = expanded + self.snapshot_files
        self.snapshot_delay = snapshot_delay
        self.snapshot_seq = snapshot_seq
        self.snapshot_repeat = snapshot_repeat
        self.snapshot_interval = snapshot_interval
        self.command_path = Path(command_path) if command_path else None
        self.command_delay = command_delay
        self.command_seq = command_seq
        self.command_repeat = max(1, command_repeat)
        self.command_interval = max(0.2, command_interval)
        self.configstrings = self._configstrings_for(self.map_name, self.gamestate_gametype.decode("ascii"))
        if configstring_file:
            self.configstrings = self._load_configstrings(Path(configstring_file))
        self.pending_oob: list[tuple[float, tuple, str]] = []
        self.origin_reader = (ClientOriginReader(follow_client_pid)
                              if follow_client_pid else None)
        self.rebuild_follower = (RebuildFollower(rebuild_follow_pid)
                                 if rebuild_follow_pid else None)
        self.state_reader = (ClientOriginReader(client_state_pid)
                             if (client_state_pid and not follow_client_pid) else None)
        self.command_every = int(server_command_every or 0)
        self.command_seq = int(server_command_seq or 0)
        self.command_text = (server_command_text or "").encode("latin-1")

    # ------------------------------------------------------------------ logging
    def log(self, event: dict) -> None:
        event = {"ts": round(time.time(), 6), **event}
        line = json.dumps(event, ensure_ascii=False, default=str)
        if self.log_path:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        # Console encodings can be GBK even when the wire payload contains
        # arbitrary Unicode. Keep the JSONL evidence in UTF-8 and escape only
        # the console representation so logging cannot kill the UDP loop.
        print(json.dumps(event, ensure_ascii=True, default=str), flush=True)

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
        # The client echoes the challenge it decodes fragments with.  Prefer
        # that value over our own, so a lost getchallenge cannot desynchronise
        # the XOR key.
        echoed = (info.get("challenge") or "").strip()
        if self.challenge_override is not None:
            # The client keeps its own challenge token (seen live at
            # connection+0x08) while the connect userinfo echoes 0; forcing the
            # observed token keeps the netchan XOR key in sync.
            peer["challenge"] = int(self.challenge_override) & 0xFFFFFFFF
            self.log({"dir": "meta", "kind": "challenge_override",
                      "value": peer["challenge"]})
        elif echoed:
            try:
                peer["challenge"] = int(echoed, 0) & 0xFFFFFFFF
            except ValueError:
                self.log({"dir": "meta", "kind": "connect_bad_challenge",
                          "value": echoed[:40]})
        # A reconnect on the same bridge port must start a fresh delivery
        # cycle; otherwise the first (failed) attempt suppresses the gamestate.
        if peer.get("gamestate_sent"):
            self.log({"dir": "meta", "kind": "connect_restart", "peer": f"{addr[0]}:{addr[1]}",
                      "previous_gamestate_sent": True})
            peer["gamestate_sent"] = False
            peer["snapshot_sent"] = False
            peer["command_sent"] = False
            peer["inband_seen"] = False
            peer["gamestateupdates"] = 0
        if "gamestate_due" not in peer or not peer.get("gamestate_sent"):
            peer["gamestate_due"] = time.monotonic() + self.delay_send
            peer["gamestate_sent"] = False
            peer["inband_seen"] = False
        if self.rebuild_follower is not None:
            self.rebuild_follower.reader._ensure_handle(force=True)
        self.log({"dir": "in", "kind": "connect", "from": f"{addr[0]}:{addr[1]}",
                  "uid": uid, "userinfo_keys": sorted(info),
                  "name": info.get("name"), "xuid": info.get("xuid"),
                  "challenge_field": info.get("challenge"),
                  "effective_challenge": peer.get("challenge"),
                  "build_field": info.get("2490")})
        gametype_text = self.gamestate_gametype.decode("ascii") or DEFAULT_GAMETYPE
        response = (f"connectResponse \\mapname\\{self.map_name}"
                    f"\\gametype\\{gametype_text}"
                    f"\\sv_maxclients\\{DEFAULT_MAXCLIENTS}"
                    f"\\protocol\\1\\shortversion\\{PROTOCOL_GENERATION}")
        # Experiments need to extend this OOB string (clientNum, sv_clientSideName,
        # spectator flags, ...) without editing code each time.  The suffix is
        # plain text so it cannot corrupt the binary gamestate.
        if self.connect_extra:
            extra = self.connect_extra
            if not extra.startswith("\\"):
                extra = "\\" + extra
            response = response + extra
            self.log({"dir": "meta", "kind": "connect_extra",
                      "value": extra[:120]})
        self.send_oob(addr, response)

    @staticmethod
    def _configstrings_for(map_name: str, gametype: str) -> tuple[tuple[int, bytes], ...]:
        """Return the default configstrings with index 0 built from map/gametype.

        The client names the loading screen from configstring 0, so overriding
        --gamestate-map only takes effect if this string is rebuilt.
        """
        rebuilt: list[tuple[int, bytes]] = []
        for index, value in DEFAULT_CONFIGSTRINGS:
            if index == 0:
                value = (f"\\g_gametype\\{gametype}\\mapname\\{map_name}").encode("ascii")
            rebuilt.append((index, bytes(value)))
        return tuple(rebuilt)

    @staticmethod
    def _load_configstrings(path: Path) -> tuple[tuple[int, bytes], ...]:
        rows = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for index, value in rows:
            out.append((int(index), str(value).encode("latin-1")))
        return tuple(out)

    def send_due_gamestates(self) -> None:
        """Send once after connect's delay, after the first client in-band packet."""
        for addr, peer in self.state.peers.items():
            due = peer.get("gamestate_due")
            if due is None or peer.get("gamestate_sent"):
                continue
            if time.monotonic() < due:
                continue
            peer["gamestate_sent"] = True
            index = min(peer.get("gamestate_count", 0), len(self.gamestate_maps) - 1)
            if self.gamestate_source == "native":
                payload = build_native_gamestate(self.registration_checksum,
                                                 configstrings=self.configstrings,
                                                 mapname=self.gamestate_maps[index],
                                                 gametype=self.gamestate_gametype)
            elif self.gamestate_source == "file":
                payload = self.gamestate_file.read_bytes()
            else:
                payload = GAMESTATE_PLAINTEXT
            if not payload:
                self.log({"dir": "meta", "kind": "gamestate_missing"})
                continue
            if self.gamestate_source == "capture" and self.checksum_feed is not None:
                original = struct.unpack_from("<I", payload, 26)[0]
                if original != 0x36E8F17B:
                    raise ValueError(f"unexpected captured checksum at offset 26: {original:#x}")
                payload = payload[:26] + struct.pack("<I", self.checksum_feed) + payload[30:]
                self.log({"dir": "meta", "kind": "checksum_feed_override",
                          "before": hex(original), "after": hex(self.checksum_feed)})
            self.log({"dir": "meta", "kind": "gamestate_source", "source": self.gamestate_source,
                      "payload_length": len(payload), "registration_checksum": hex(self.registration_checksum),
                      "configstrings": [[index, value.decode("latin-1")]
                                        for index, value in self.configstrings][:8],
                      "configstring_count": len(self.configstrings),
                      "payload_head": payload[:96].hex()})
            # A fresh natural connection starts near sequence 1. The verified
            # regression run accepted gamestate sequence 3 and acknowledged it;
            # starting at 100000 left the client at state 7 with ack 1.
            seq = 3 + peer.get("gamestate_count", 0)
            peer["gamestate_count"] = peer.get("gamestate_count", 0) + 1
            peer["last_server_seq"] = seq
            self._send_fragments(addr, peer, payload, seq, "gamestate")
            if self.snapshot_files:
                # Honour the configured delay so trials can separate early
                # delivery from payload validity. The known hybrid control
                # reaches state 10 with a 20-second delay.
                peer["snapshot_due"] = time.monotonic() + self.snapshot_delay
                peer["snapshot_sent"] = False
                peer["snapshot_index"] = 0
            if self.command_path:
                peer["command_due"] = time.monotonic() + self.command_delay
                peer["command_count"] = 0
            if self.oob_command:
                peer["oob_due"] = time.monotonic() + self.oob_delay
            if self.gamestate_repeat and peer["gamestate_count"] < self.gamestate_repeat:
                peer["gamestate_sent"] = False
                peer["gamestate_due"] = time.monotonic() + self.gamestate_interval

    def send_due_oob(self) -> None:
        """Send the configured OOB command once per peer after the delay."""
        if not self.oob_command:
            return
        for addr, peer in self.state.peers.items():
            due = peer.get("oob_due")
            if due is None or time.monotonic() < due:
                continue
            self.send_oob(addr, self.oob_command)
            peer["oob_due"] = None

    def send_due_commands(self) -> None:
        """Send the captured server-command stream once per configured repeat."""
        if not self.command_path:
            return
        for addr, peer in self.state.peers.items():
            due = peer.get("command_due")
            if due is None or time.monotonic() < due:
                continue
            count = peer.get("command_count", 0)
            if count >= self.command_repeat:
                peer["command_due"] = None
                continue
            try:
                data = self.command_path.read_bytes()
            except OSError as error:
                peer["command_due"] = None
                self.log({"dir": "meta", "kind": "command_missing", "error": str(error)})
                continue
            seq = self.command_seq + count
            payload = b"\x00\x00\x00\x00" + data
            self.log({"dir": "meta", "kind": "command_source",
                      "path": str(self.command_path), "payload_length": len(payload),
                      "seq": seq, "repeat": count + 1, "payload_head": payload[:48].hex()})
            self._send_fragments(addr, peer, payload, seq, "command")
            peer["command_count"] = count + 1
            peer["command_due"] = time.monotonic() + self.command_interval

    @staticmethod
    def _xor_cycle(data: bytes, key: int) -> str:
        """XOR a byte string with the four bytes of `key`, cycling, and hex-dump it.

        Experiment helper: the client ciphers in-band bodies, and the server's own
        sender uses `(challenge ^ seq) & 0xFF`.  Trying the challenge-derived keys
        lets us see whether the decrypted head looks like a sane `usercmd`.
        """
        kb = [(key >> (8 * i)) & 0xFF for i in range(4)]
        return bytes(b ^ kb[i % 4] for i, b in enumerate(data)).hex()

    def _send_fragments(self, addr: tuple, peer: dict, payload: bytes, seq: int,
                        kind: str, frag_size: int = 1162) -> None:
        peer["last_server_seq"] = seq
        count = (len(payload) + frag_size - 1) // frag_size
        seq_word = seq | 0x80000000
        key = ((peer.get("challenge") or 0) ^ seq) & 0xFF
        if count <= 1 and kind == "command":
            # Captured small reliable commands use a bare plaintext payload.
            # Gamestate and snapshot remain single-fragment netchan messages:
            # regression-gs.jsonl reached state 10 with a 89-byte gamestate
            # wrapped in one fragment. Sending it bare stalled at state 7.
            self.sock.sendto(bytes(payload), addr)
            self.state.counters["inband_sent"] += 1
            self.log({"dir": "out", "kind": "single", "message": kind,
                      "to": f"{addr[0]}:{addr[1]}", "seq": seq,
                      "length": len(payload), "payload_head": payload[:32].hex()})
            return
        for index in range(count):
            chunk = payload[index * frag_size:(index + 1) * frag_size]
            data = bytearray(chunk)
            for i in range(4 if index == 0 else 0, len(data)):
                data[i] ^= key
            # The verified 1649370 regression packet starts directly with the
            # 10-byte fragment header (gamestate seq 3, 89-byte chunk, 99 bytes
            # total). A prepended u16 length made the client ignore it at state 7.
            header = (struct.pack("<I", seq_word) + bytes([index, count - 1])
                      + struct.pack("<HH", frag_size, len(chunk)))
            packet = header + data
            self.sock.sendto(packet, addr)
            self.state.counters["inband_sent"] += 1
            self.log({"dir": "out", "kind": "fragment", "message": kind,
                      "to": f"{addr[0]}:{addr[1]}",
                      "seq": seq, "index": index, "count": count,
                      "stride": frag_size, "chunk": len(chunk), "length": len(packet)})

    def send_due_snapshots(self) -> None:
        """Send the staged snapshot files in order; optionally keep repeating the last."""
        if not self.snapshot_files:
            return
        for addr, peer in self.state.peers.items():
            due = peer.get("snapshot_due")
            if due is None or time.monotonic() < due:
                continue
            index = peer.get("snapshot_index", 0)
            if index < len(self.snapshot_files):
                path = self.snapshot_files[index]
            elif self.snapshot_repeat:
                path = self.snapshot_files[-1]
            else:
                peer["snapshot_due"] = None
                continue
            try:
                data = path.read_bytes()
            except OSError as error:
                peer["snapshot_due"] = None
                self.log({"dir": "meta", "kind": "snapshot_missing", "error": str(error)})
                continue
            payload = b"\x00\x00\x00\x00" + data
            if not self.snapshot_preserve_time and len(payload) >= 9 and payload[4] == 0:
                server_time = 72192 + index * 500
                payload = payload[:5] + struct.pack("<I", server_time) + payload[9:]
            if self.rebuild_follower is not None:
                # The static path below stamps serverTime as 72192 + index*500 and
                # that cadence is what the client accepts (r576 kept net=10 for
                # minutes).  Using a different step here made consecutive frames
                # disagree about time, and the client dropped to the lobby.
                dynamic = self.rebuild_follower.frame(server_time=72192 + index * 500,
                                                      dt=self.snapshot_interval)
                if dynamic is not None:
                    payload = b"\x00\x00\x00\x00" + dynamic
                    if index % 25 == 0:
                        self.log({"dir": "meta", "kind": "rebuild_follow",
                                  "origin": self.rebuild_follower.last_origin, "index": index})
            if self.origin_reader is not None:
                before = payload[0x0F:0x1C]
                payload = self.origin_reader.apply(payload)
                if payload[0x0F:0x1C] != before and index % 25 == 0:
                    self.log({"dir": "meta", "kind": "origin_follow",
                              "seq": self.snapshot_seq + index,
                              "origin": list(struct.unpack("<fff", payload[0x0F:0x0F + 12]))})
            seq = self.snapshot_seq + index
            gate = self.state_reader or self.origin_reader
            ready = True if gate is None else gate.is_active()
            if self.command_every and index % self.command_every == 0 and ready:
                # svc_serverCommand: [0x05][sequence u32][text NUL].  Without it
                # the client's serverCommandSequence never advances, the
                # unconfirmed-command window exceeds the prediction limit and
                # CL_PredictMovement is skipped, so held movement never moves.
                self.command_seq += 1
                if self.origin_reader is not None:
                    cmd = self.origin_reader.cmd_number()
                    if cmd is not None:
                        # Keep the unconfirmed-command window small but non-zero:
                        # CL_PredictMovement is skipped once cmdNumber -
                        # serverCommandSequence exceeds 32.
                        self.command_seq = max(self.command_seq, cmd - 4)
                # svc_serverCommand = 1: [0x01][sequence u32][text NUL].  The
                # handler at 0x4737E0 rejects non-increasing sequences and stores
                # the text into conn+0x80154[sequence & 0x1FF].
                command = (b"\x01" + struct.pack("<I", self.command_seq)
                           + self.command_text + b"\x00")
                self._send_fragments(addr, peer, b"\x00\x00\x00\x00" + command,
                                     seq - 1, "servercmd")
            self._send_fragments(addr, peer, payload, seq, "snapshot")
            peer["snapshot_index"] = index + 1
            if index + 1 < len(self.snapshot_files):
                peer["snapshot_due"] = time.monotonic() + self.snapshot_interval
            elif self.snapshot_repeat and index + 1 < self.snapshot_repeat:
                peer["snapshot_due"] = time.monotonic() + self.snapshot_interval
            else:
                peer["snapshot_due"] = None
            self.log({"dir": "meta", "kind": "snapshot_source",
                      "path": str(path), "payload_length": len(payload),
                      "seq": seq, "file_index": index, "payload_head": payload[:64].hex()})

    def on_stats(self, addr: tuple, args: list[str], peer: dict) -> None:
        self.state.counters["stats"] += 1
        challenge = peer.get("challenge") or 0
        self.log({"dir": "in", "kind": "stats", "from": f"{addr[0]}:{addr[1]}",
                  "args": args, "challenge": challenge})
        # Echo the challenge the client was given: a bare 0 does not let the
        # client confirm that it is talking to the server that issued it.
        # The client only accepts statResponse in state 5, but it sends stats
        # in the same burst as connect (state 4).  Re-send the reply on a few
        # offsets so one of them lands after the state transition regardless of
        # frame timing; extra copies in later states are ignored.
        #
        # The early offsets matter: the client retries `stats` about every
        # 103 ms and gave up after 7 tries (0.72 s) in the Round 43/44 runs.
        # With the first reply at 0.8 s it never arrived before the client had
        # already exhausted its retries and crashed, so answer immediately and
        # keep a few closely spaced copies during that first second.
        now = time.monotonic()
        for offset in (0.0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 2.0, 4.0):
            self.pending_oob.append((now + offset, addr, f"statResponse {challenge}"))

    def flush_pending_oob(self) -> None:
        if not self.pending_oob:
            return
        now = time.monotonic()
        remaining = []
        for due, addr, text in self.pending_oob:
            if now >= due:
                self.send_oob(addr, text)
            else:
                remaining.append((due, addr, text))
        self.pending_oob = remaining

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
            elif command == "gamestateupdate":
                # The client asks for gamestate refreshes while it loads the
                # map; the last request is the natural moment to deliver the
                # first snapshot (the client is in state 9 by then).
                count = peer.get("gamestateupdates", 0) + 1
                peer["gamestateupdates"] = count
                self.log({"dir": "in", "kind": "gamestateupdate", "from": f"{addr[0]}:{addr[1]}",
                          "count": count, "args": args})
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
            peer["inband_seen"] = True
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
                      "body_head": body[:2048].hex(),
                      "body_dec_challenge": self._xor_cycle(body[:2048], peer.get("challenge") or 0),
                      "body_dec_ch_ack": self._xor_cycle(
                          body[:2048], ((peer.get("challenge") or 0) ^ (server_id << 24)
                                      ^ (message_ack & 0xFFFFFFFF)) & 0xFFFFFFFF),
                      "body_nonzero": sum(1 for b in body[:2048] if b) > 0})
        else:
            self.log({"dir": "in", "kind": "inband_short", "from": f"{addr[0]}:{addr[1]}",
                      "length": len(data), "hex": data[:64].hex()})

    # ------------------------------------------------------------------ serving
    def serve(self) -> None:
        self.log({"dir": "meta", "kind": "start", "port": self.sock.getsockname()[1],
                  "generation": PROTOCOL_GENERATION, "map": self.map_name})
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                self.flush_pending_oob()
                self.send_due_gamestates()
                self.send_due_commands()
                self.send_due_snapshots()
                self.send_due_oob()
                continue
            except OSError:
                break
            self.flush_pending_oob()
            self.handle(data, addr)
            self.send_due_gamestates()
            self.send_due_commands()
            self.send_due_snapshots()
            self.send_due_oob()
        self.log({"dir": "meta", "kind": "stop", "counters": self.state.counters})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=28971)
    parser.add_argument("--log", default="runs/gs.jsonl")
    parser.add_argument("--delay-send", type=float, default=0.0,
                        help="seconds after connect before sending gamestate")
    parser.add_argument("--checksum-feed", type=lambda value: int(value, 0),
                        help="experimental uint32 replacement at gamestate offset 26")
    parser.add_argument("--gamestate-source", choices=("native", "capture", "file"), default="native")
    parser.add_argument("--gamestate-file", default=None,
                        help="complete plaintext payload, including four-byte reliable ack")
    parser.add_argument("--gamestate-repeat", type=int, default=0)
    parser.add_argument("--gamestate-interval", type=float, default=20.0)
    parser.add_argument("--gamestate-map", default=None)
    parser.add_argument("--gamestate-gametype", default=None)
    parser.add_argument("--oob-command", default=None)
    parser.add_argument("--oob-delay", type=float, default=30.0)
    parser.add_argument("--match-duration", type=float, default=None,
                        help="alias for --oob-delay: seconds from connect to the automatic end-of-match disconnect")
    parser.add_argument("--registration-checksum", type=lambda value: int(value, 0),
                        default=0xFFB56D7E)
    parser.add_argument("--challenge-override", type=lambda value: int(value, 0),
                        default=None,
                        help="force the netchan XOR challenge (client token at connection+0x08)")
    parser.add_argument("--snapshot-file", default=None,
                        help="service message bytes (svc 0 + body + EOF) sent after gamestate")
    parser.add_argument("--snapshot-delay", type=float, default=3.0,
                        help="seconds after gamestate before the snapshot is sent")
    parser.add_argument("--snapshot-seq", type=int, default=4)
    parser.add_argument("--snapshot-preserve-time", action="store_true",
                        help="keep the snapshot body's recorded serverTime")
    parser.add_argument("--rebuild-follow-pid", type=int, default=None,
                        help="encode each snapshot from the client predicted origin")
    parser.add_argument("--follow-client-pid", type=int, default=None,
                        help="mirror this client process's predicted origin into every snapshot")
    parser.add_argument("--client-state-pid", type=int, default=None,
                        help="read-only client pid used to gate server commands on net_state==10")
    parser.add_argument("--server-command-every", type=int, default=0,
                        help="send one svc_serverCommand every N snapshots (0 = never)")
    parser.add_argument("--server-command-seq", type=int, default=0,
                        help="first svc_serverCommand sequence number")
    parser.add_argument("--server-command-text", default=None,
                        help="text carried by svc_serverCommand (empty is harmless)")
    parser.add_argument("--snapshot-repeat", type=int, default=0,
                        help="total snapshot sends; 0 = send once")
    parser.add_argument("--snapshot-interval", type=float, default=0.5,
                        help="seconds between repeated snapshots")
    parser.add_argument("--snapshot-dir", default=None,
                        help="directory of *.bin frames sent in filename order; "
                             "each frame is repeated --snapshot-frame-repeat times")
    parser.add_argument("--snapshot-frame-repeat", type=int, default=1,
                        help="how many consecutive sends each --snapshot-dir frame gets")
    parser.add_argument("--command-file", default=None,
                        help="server-command service stream sent before the snapshot")
    parser.add_argument("--command-delay", type=float, default=2.0,
                        help="seconds after gamestate before server commands")
    parser.add_argument("--command-seq", type=int, default=4)
    parser.add_argument("--configstring-file", default=None,
                        help="JSON [[index, value], ...] replacing the built-in configstrings")
    parser.add_argument("--connect-extra", default=None,
                        help="extra \\key\\value text appended to connectResponse "
                             "(e.g. \"\\\\clientNum\\\\0\"); purely experimental")
    parser.add_argument("--command-repeat", type=int, default=1,
                        help="how many times to send the server-command stream")
    parser.add_argument("--command-interval", type=float, default=5.0,
                        help="seconds between repeated server-command streams")
    args = parser.parse_args()
    if args.gamestate_map:
        for part in args.gamestate_map.split(","):
            name = part.strip()
            if not name:
                parser.error("--gamestate-map contains an empty name")
            if len(name) > 32 or any(ch in name for ch in '\\/:*?"<>| '):
                parser.error(f"--gamestate-map {name!r} is not a plain map name")
    if args.snapshot_file:
        from pathlib import Path as _Path
        for part in args.snapshot_file.split(","):
            if part.strip() and not _Path(part.strip()).exists():
                parser.error(f"--snapshot-file {part.strip()!r} does not exist")
    if args.gamestate_source == "file" and (not args.gamestate_file or not Path(args.gamestate_file).is_file()):
        parser.error("--gamestate-source file requires an existing --gamestate-file")
    if args.delay_send < 0:
        parser.error("--delay-send must be nonnegative")
    if args.checksum_feed is not None and not 0 <= args.checksum_feed <= 0xFFFFFFFF:
        parser.error("--checksum-feed must be a uint32")
    if args.snapshot_delay < 0:
        parser.error("--snapshot-delay must be nonnegative")
    if not 0 < args.snapshot_seq <= 0x7FFFFFFF:
        parser.error("--snapshot-seq must be a positive 31-bit integer")
    if args.snapshot_repeat < 0:
        parser.error("--snapshot-repeat must be nonnegative")
    if args.snapshot_interval <= 0:
        parser.error("--snapshot-interval must be positive")
    if args.snapshot_frame_repeat < 1:
        parser.error("--snapshot-frame-repeat must be at least 1")
    if args.snapshot_dir and not Path(args.snapshot_dir).is_dir():
        parser.error(f"--snapshot-dir {args.snapshot_dir!r} is not a directory")
    if args.command_delay < 0:
        parser.error("--command-delay must be nonnegative")
    if not 0 < args.command_seq <= 0x7FFFFFFF:
        parser.error("--command-seq must be a positive 31-bit integer")
    server = GameServer(args.port, args.log, args.delay_send, args.checksum_feed,
                        args.gamestate_source, args.registration_checksum, args.challenge_override,
                        args.snapshot_file, args.snapshot_delay, args.snapshot_seq,
                        args.snapshot_repeat, args.snapshot_interval,
                        args.command_file, args.command_delay, args.command_seq,
                        args.configstring_file, args.command_repeat, args.command_interval,
                        args.gamestate_repeat, args.gamestate_interval, args.gamestate_map,
                        args.gamestate_gametype, args.oob_command,
                        args.oob_delay if args.match_duration is None else args.match_duration,
                        args.gamestate_file, args.connect_extra, args.snapshot_preserve_time,
                        args.follow_client_pid, args.client_state_pid, args.server_command_every,
                        args.server_command_seq, args.server_command_text,
                        args.snapshot_dir, args.snapshot_frame_repeat,
                        args.rebuild_follow_pid)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
