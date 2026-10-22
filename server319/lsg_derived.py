"""Build 1649370 LSG responder using transcript-derived session keys.

The handshake and client-frame verifier are qualified by local captures. Task
responses below are explicitly provisional until consumed by the target client.
Unknown requests remain visible in the run log and receive no fake success.
"""

from __future__ import annotations

import hashlib
import hmac
import dataclasses
import json
from pathlib import Path
import os
import socket
import struct
import threading
import time

from .auth import AuthServer
from .lsg_crypto import (LsgProtocolError, build_server_frame85,
                         build_server_frame85_preamble, derive_keys,
                         parse_client_frame85)
from .profile import default_store
from .ticket import SESSION_KEY

GATE_MARK = 0x1122334455667788
MAX_FRAME = 1 << 20


def _read_exact(conn: socket.socket, size: int) -> bytes:
    out = bytearray()
    while len(out) < size:
        part = conn.recv(size - len(out))
        if not part:
            raise EOFError("peer_closed")
        out.extend(part)
    return bytes(out)


def _read_frame(conn: socket.socket) -> bytes:
    head = _read_exact(conn, 4)
    size = struct.unpack("<I", head)[0]
    if size > MAX_FRAME:
        raise LsgProtocolError("oversize_frame")
    return head + _read_exact(conn, size) if size else head


def _typed_u32(value: int) -> bytes:
    return b"\x08" + struct.pack("<I", value)


def decode_typed_fields(buf: bytes, limit: int = 8) -> str:
    """Decode the typed (bdv) argument list of a client task request.

    Mirrors the codec in codol-node/lsg.js (TypeReader): every value carries a
    one-byte type tag -- 0x03 byte, 0x06 u16, 0x08 u32, 0x0a u64, 0x10
    NUL-terminated string, 0x13 blob (plus an extra 0x08 length tag).  Only for
    readable evidence, so an unknown tag ends the list instead of raising.
    """
    out: list[str] = []
    offset = 0
    while offset < len(buf) and len(out) < limit:
        tag = buf[offset]
        offset += 1
        if tag == 0x03:
            if offset >= len(buf):
                out.append("truncated")
                break
            out.append(f"u8({buf[offset]})")
            offset += 1
        elif tag == 0x06:
            if offset + 2 > len(buf):
                out.append("truncated")
                break
            out.append(f"u16({struct.unpack_from('<H', buf, offset)[0]})")
            offset += 2
        elif tag == 0x08:
            if offset + 4 > len(buf):
                out.append("truncated")
                break
            out.append(f"u32({struct.unpack_from('<I', buf, offset)[0]})")
            offset += 4
        elif tag == 0x0A:
            if offset + 8 > len(buf):
                out.append("truncated")
                break
            out.append(f"u64({struct.unpack_from('<Q', buf, offset)[0]})")
            offset += 8
        elif tag == 0x10:
            end = buf.find(b"\x00", offset)
            if end < 0:
                end = len(buf)
            text = buf[offset:end]
            if text and all(32 <= byte < 127 for byte in text):
                out.append('str("%s")' % text.decode("latin-1"))
            else:
                out.append("str_hex(%s)" % text.hex())
            offset = end + 1
        elif tag == 0x13:
            if offset < len(buf) and buf[offset] == 0x08 and offset + 5 <= len(buf):
                size = struct.unpack_from("<I", buf, offset + 1)[0]
                out.append(f"blob({size}B)")
                offset += 5 + size
            else:
                out.append("blob(malformed)")
                break
        else:
            out.append(f"tag(0x{tag:02x})")
            break
    return ",".join(out)


def _typed_u64(value: int) -> bytes:
    return b"\x0a" + struct.pack("<Q", value)


def candidate_svc71_task4_reply(transaction_id: int = 1) -> bytes:
    """Candidate bdService envelope from local reference; unconsumed on 1649370."""
    return (_typed_u64(transaction_id) + _typed_u32(0) + b"\x03\x04"
            + _typed_u32(1) + _typed_u32(1) + _typed_u32(0))


def candidate_empty_success_reply(transaction_id: int, task_id: int) -> bytes:
    """1604220 lobby fallback shape, provisional for observed 1649370 tasks."""
    if not 0 <= task_id <= 255:
        raise LsgProtocolError("candidate_task_id")
    return _typed_u64(transaction_id) + _typed_u32(0) + b"\x03" + bytes([task_id]) + _typed_u32(0)


def _typed_u16(value: int) -> bytes:
    return b"\x06" + struct.pack("<H", value)


def _typed_string(text: bytes) -> bytes:
    """0x10 tag + NUL-terminated bytes (bdsvc319's string encoding)."""
    return b"\x10" + text + b"\x00"


def _typed_i32(value: int) -> bytes:
    return b"\x07" + struct.pack("<i", value)


def _typed_bool(value: bool) -> bytes:
    return b"\x01" + (b"\x01" if value else b"\x00")


def _typed_blob(data: bytes) -> bytes:
    """0x13 blob tag, 0x08 length tag, LE32 length, payload."""
    return b"\x13\x08" + struct.pack("<I", len(data)) + data


def make_room_common_address(ip: bytes = b"\x7f\x00\x00\x01",
                             port: int = 28969, layout: str = "v4") -> bytes:
    """37-byte bdCommonAddr.

    `v4`  = 1 byte kind + 32 byte address + LE32 port (IPv4 in bytes 0..3).
    `v46` = 1 byte kind + 16 byte IPv6 + 16 byte IPv4 (in the last 4) + LE32
            port, the classic dual-stack bdCommonAddr layout.  Kept switchable
            because the listing record only carries the opaque 37-byte blob.
    """
    if layout == "v46":
        address = bytearray(32)
        address[28:32] = ip
        return b"\x00" + bytes(address) + struct.pack("<I", port)
    address = bytearray(32)
    address[0:4] = ip
    return b"\x00" + bytes(address) + struct.pack("<I", port)


def make_room_listing_record(room_name: bytes = b"AI-Room", channel_id: int = 1,
                             session_id: int = 1, max_players: int = 12,
                             current_players: int = 1,
                             owner_uid: int = 1, owner_name: bytes = b"Player",
                             ip: bytes = b"\x7f\x00\x00\x01",
                             port: int = 28969,
                             security_key: bytes = bytes(16),
                             addr_layout: str = "v4",
                             session_kind: int = 0,
                             int_override: int | None = None) -> bytes:
    """One `21/13`/`21/5 query4` room listing record.

    Field order follows 他人文件参考/codol3333服务端开发文档/
    ROOM_BROWSER_PREPARATION.md "列表回包与身份": 37-byte common address,
    8-byte session id, session kind, max/current players, room name, owner
    uid/name, 3x int32, uint32, 3x int32, 16-byte security key, 11x int32,
    uint64 channel id, 2x int32.  The record has no NoType terminator.

    `addr_layout`/`session_kind`/`int_override` exist only to A/B the fields
    the client filters on; the defaults keep the documented shape.
    """
    if len(room_name) > 24:
        raise ValueError("room_name_too_long")
    if len(security_key) != 16:
        raise ValueError("security_key_must_be_16")
    out = bytearray()
    out += _typed_blob(make_room_common_address(ip, port, layout=addr_layout))
    out += _typed_blob(struct.pack("<Q", session_id))
    out += _typed_u32(session_kind)           # session kind: MP room = 0
    out += _typed_u32(max_players)
    out += _typed_u32(current_players)
    out += _typed_string(room_name)
    out += _typed_u64(owner_uid)
    out += _typed_string(owner_name)
    for _ in range(3):
        out += _typed_i32(int_override if int_override is not None else 0)
    out += _typed_u32(0)
    for _ in range(3):
        out += _typed_i32(int_override if int_override is not None else 0)
    out += _typed_blob(security_key)
    for _ in range(11):
        out += _typed_i32(int_override if int_override is not None else 0)
    out += _typed_u64(channel_id)
    for _ in range(2):
        out += _typed_i32(int_override if int_override is not None else 0)
    return bytes(out)


def _room_hmac_key(mode: str, keys) -> bytes | None:
    """Pick the key for the reply's 8-byte bdService HMAC tail.

    The key was verified at runtime: calling the client's `0xBA02A0` returns
    exactly the LSG-derived 20-byte `server_mac` (the server-frame HMAC key), so
    only the *coverage* of the message HMAC is still open.
    """
    if mode in ("server_mac", "burst"):
        return keys.server_mac
    if mode == "client_mac":
        return keys.client_mac
    return None


def append_message_hmac(payload: bytes, key: bytes, mode: str = "payload",
                        inner_type: int = 1) -> bytes:
    """Append the 8-byte bdService message HMAC under different coverage rules.

    `payload` is the bdService envelope before the HMAC tail; the length header
    and inner type byte are the ones the frame builder will use.
    """
    length = len(payload) + 8
    head = struct.pack("<I", length) + bytes([inner_type])
    if mode == "payload":
        data = payload
    elif mode == "frame_plain":
        data = head + payload
    elif mode == "frame_plain_padded":
        body = head + payload
        data = body + bytes((-len(body)) % 16)
    elif mode == "payload_skip4":
        data = payload[4:]
    elif mode == "payload_no_tail8":
        data = payload[:-8] if len(payload) > 8 else payload
    elif mode == "length_payload":
        data = struct.pack("<I", length) + payload
    else:
        raise ValueError(f"unknown hmac coverage {mode!r}")
    return payload + hmac.digest(key, data, "sha1")[:8]


def _room_task_id(service: int, task: int) -> int:
    """Task byte for the room reply; ROOM_TASK_SOURCE may be a number."""
    raw = os.environ.get("ROOM_TASK_SOURCE", "task")
    if raw.isdigit():
        return int(raw)
    return {"service": service, "action": 0x26}.get(raw, task)


def room_listing_reply(transaction_id: int, task_id: int = 13,
                       room_name: bytes = b"AI-Room", channel_id: int = 1,
                       port: int = 28969, records: list[bytes] | None = None,
                       count_mode: str = "double", hmac_key: bytes | None = None,
                       **record_kwargs) -> bytes:
    """bdService reply carrying room listing records (page-sized list allowed).

    `count_mode="double"` mirrors the reference server's count/count quirk;
    `"single"` writes the object count once, which is the other shape the
    Demonware bdService envelope accepts.  `hmac_key` appends the 8-byte
    HMAC-SHA1 tail that the client's 0xBA3710 message parser compares.
    """
    if records is None:
        records = [make_room_listing_record(room_name=room_name, channel_id=channel_id,
                                            port=port, **record_kwargs)]
    out = bytearray()
    out += _typed_u64(transaction_id) + _typed_u32(0) + b"\x03" + bytes([task_id])
    out += _typed_u32(len(records))
    if count_mode != "single":
        out += _typed_u32(len(records))
    for record in records:
        out += record
    if hmac_key:
        out += hmac.digest(hmac_key, bytes(out), "sha1")[:8]
    return bytes(out)


def room_list_variant(index: int, room_name: bytes = b"AI-Room",
                      channel_id: int = 1, port: int = 28969,
                      addr_layout: str | None = None) -> tuple[list[bytes], str]:
    """A/B variants for the room listing record.

    0 baseline, 1 full page (pagination ack probe), 2 IPv4+IPv6 address block,
    3 session kind 4, 4 documented build value in every int32, 5 zero-length
    owner name.  `addr_layout` overrides the common-address layout for all
    variants (the record only carries the opaque 37-byte blob).
    """
    def one(**kwargs):
        if addr_layout:
            kwargs.setdefault("addr_layout", addr_layout)
        return make_room_listing_record(room_name=room_name, channel_id=channel_id,
                                        port=port, **kwargs)
    variant = index % 6
    if variant == 0:
        return [one()], "baseline"
    if variant == 1:
        return [one() for _ in range(30)], "page_fill_30"
    if variant == 2:
        return [one(addr_layout="v46")], "addr_v46"
    if variant == 3:
        return [one(session_kind=4)], "session_kind_4"
    if variant == 4:
        return [one(int_override=-688906341)], "int_build"
    return [one(owner_name=b"")], "owner_name_empty"


def make_server_entry(ip: bytes = b"\x7f\x00\x00\x01", port: int = 8466,
                      name: bytes = b"TestServer") -> bytes:
    """bdMatchMaking server entry, byte-for-byte as bdsvc319.make_server_entry.

    114 bytes when the name is TestServer. bdsvc319 builds it with the same
    typed-value codec this module already uses (0x08 u32, 0x06 u16, 0x10 str).
    """
    out = bytearray()
    out += _typed_u32(struct.unpack("<I", ip)[0])
    out += _typed_u16(port)
    out += _typed_u16(0)
    for _ in range(5):
        out += _typed_u32(0)
    out += _typed_u32(0x9D)
    for _ in range(5):
        out += _typed_u32(0)
    out += _typed_u32(1)
    out += _typed_u32(1)
    out += _typed_string(name)
    out += _typed_u32(0)
    out += _typed_u32(struct.unpack("<I", ip)[0])
    out += _typed_u16(port)
    out += _typed_u16(0)
    out += _typed_u32(0)
    out += _typed_u32(0)
    return bytes(out)


def candidate_svc71_task9_reply(transaction_id: int = 1,
                                port: int = 8466) -> bytes:
    """svc71/task9 FindSessions: one bdMatchMaking entry for 127.0.0.1:port."""
    entry = make_server_entry(port=port)
    return (_typed_u64(transaction_id) + _typed_u32(0) + b"\x03\x09"
            + _typed_u32(1) + _typed_u32(1) + entry)


def terminal_unavailable_reply(transaction_id: int, error: int = 4) -> bytes:
    """bdService failure envelope; no result object.

    SERVICE_INITIALIZATION.md: the client pops the head task for every kind=0x86
    response, so *every* request must receive exactly one reply and replies must
    follow request order.  Error 4 is what the target itself uses for
    "unsupported / deserialize failed"; skipping a request desynchronises every
    later reply (which is why the earlier room-list replies were ignored).
    """
    return _typed_u64(transaction_id) + _typed_u32(error)


class DerivedLsgServer(AuthServer):
    def __init__(self, *args, token_marker: int = 0x00,
                 observed71_empty: bool = False, profile_store=None,
                 session_key: bytes = SESSION_KEY, allow_auth_tls: bool = False,
                 **kwargs):
        super().__init__(*args, **kwargs)
        if token_marker not in (0x00, 0xAB):
            raise ValueError("token_marker")
        self.token_marker = token_marker
        self.observed71_empty = observed71_empty
        if len(session_key) != 24:
            raise ValueError("session_key must be 24 bytes")
        self.session_key = session_key
        self.allow_auth_tls = allow_auth_tls
        self.profile_store = profile_store or default_store()
        self.user_id = os.environ.get("LSG_USER_ID", "1")
        self.profile_store.get_or_create(self.user_id)

    def _handle(self, conn: socket.socket) -> None:
        session = self._new_session()
        try:
            conn.settimeout(10)
            head = conn.recv(16, socket.MSG_PEEK)
            if head and head[0] in (0x16, 0x80):
                if self.allow_auth_tls:
                    AuthServer._handle(self, conn)
                    return
                self.evidence.write("unsupported_tls_lsg", session)
                return
            hello = _read_exact(conn, 28)
            self.evidence.write("plaintext_frame", session, body_len=len(hello),
                                body_sha256=hashlib.sha256(hello).hexdigest(),
                                body_hex=hello.hex())
            gate_body = (b"\x01\x81" + struct.pack("<I", 220)
                         + struct.pack("<Q", GATE_MARK) + os.urandom(8))
            gate = struct.pack("<I", len(gate_body)) + gate_body
            conn.sendall(gate)
            self.evidence.write("gate_reply", session, reply_hex=gate.hex())
            client_auth = _read_frame(conn)
            self.evidence.write("plaintext_frame2", session,
                                body_len=len(client_auth),
                                body_sha256=hashlib.sha256(client_auth).hexdigest(),
                                body_hex=client_auth.hex())
            keys = derive_keys(hello, gate, client_auth, self.session_key)
            key_dump_done = False
            self.evidence.write("session_derived", session,
                                reason="challenge_verified; client-memory-read=false")
            token = (struct.pack("<I", 10) + bytes([self.token_marker, 0x83])
                     + keys.challenge[8:])
            conn.sendall(token)
            self.evidence.write("token_reply", session, reply_hex=token.hex())
            counter = int(os.environ.get("LSG_TID_START", "1"))
            # PROGRESS.md: the reference server pushes a ZEROFRAME (bare u32 0)
            # every 30 s to keep the lobby alive. Send it from a helper thread so
            # the recv loop stays blocking.
            idle_interval = float(os.environ.get("LSG_ZEROFRAME", "30"))
            stop_zero = threading.Event()

            def _zero_loop() -> None:
                while not stop_zero.wait(idle_interval):
                    try:
                        conn.sendall(bytes(4))
                        self.evidence.write("zero_frame", session)
                    except OSError:
                        return

            if idle_interval > 0:
                threading.Thread(target=_zero_loop, daemon=True).start()
            # Optional: push a room-list frame without being asked. Observed
            # sessions stop after svc71/task4 and only send keepalives, so the
            # list is pushed for the client to render. Opt-in via
            # LSG_PUSH_21_5=<seconds> because an unsolicited frame can also
            # confuse the session.
            push_delay = float(os.environ.get("LSG_PUSH_21_5", "0"))
            if push_delay > 0:
                def _push_room_list() -> None:
                    time.sleep(push_delay)
                    try:
                        payload = (candidate_svc71_task9_reply(
                            1, int(os.environ.get("FINDSESS_PORT", "8466")))
                            .replace(b"\x03\x09", b"\x03\x05", 1))
                        frame = build_server_frame85(keys, payload, counter=1,
                                                     iv=os.urandom(16))
                        conn.sendall(frame)
                        self.evidence.write("pushed_room_list", session,
                                            reply_hex=frame.hex(),
                                            reason=f"unsolicited svc21/task5 after {push_delay:g}s")
                    except OSError:
                        pass

                threading.Thread(target=_push_room_list, daemon=True).start()
            # The target remains silent after its first task while it waits for
            # further lobby state. A short recv timeout is a server-side close,
            # which the client surfaces as [100] after exactly that interval.
            conn.settimeout(75)
            while True:
                frame = _read_frame(conn)
                if frame == bytes(4):
                    # Zero-length control frame: the client's keepalive. Answer
                    # with the same bare u32 0 (lobby.py keeps the channel alive
                    # this way); staying silent makes it stall after task4.
                    self.evidence.write("idle_control", session)
                    if os.environ.get("LSG_IDLE_REPLY", "0") != "0":
                        conn.sendall(bytes(4))
                        self.evidence.write("idle_reply", session)
                    continue
                if os.environ.get("LSG_DUMP_KEYS") == "1" and not key_dump_done:
                    # Dump the derived session keys so captured client frames can
                    # be decrypted offline later. Written to a sidecar file rather
                    # than the evidence log: EvidenceWriter rejects unknown fields
                    # with ValueError, and that exception is not caught by the
                    # session handler, so putting it there kills the connection.
                    key_dump_done = True
                    try:
                        sidecar = Path(str(self.evidence.path) + ".keys.jsonl")
                        record = {f.name: getattr(keys, f.name).hex()
                                  for f in dataclasses.fields(keys)
                                  if isinstance(getattr(keys, f.name), (bytes, bytearray))}
                        sidecar.parent.mkdir(parents=True, exist_ok=True)
                        with sidecar.open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps({"keys": record}) + "\n")
                    except Exception as exc:  # never break the session for a dump
                        print(f"key dump failed: {exc}", file=sys.stderr)
                self.evidence.write("client_frame", session, body_len=len(frame),
                                    body_sha256=hashlib.sha256(frame).hexdigest(),
                                    body_hex=frame.hex())
                received_counter, inner_type, payload = parse_client_frame85(frame, keys)
                self.evidence.write("client_frame_verified", session,
                                    reason=f"counter={received_counter} inner={inner_type:#x} "
                                           f"payload_len={len(payload)}")
                if inner_type != 0x86 or len(payload) < 3:
                    self.evidence.write("unhandled_inner", session,
                                        reason=f"inner={inner_type:#x}")
                    continue
                service, tag, task = payload[:3]
                if tag != 0x03:
                    self.evidence.write("unhandled_task_header", session,
                                        reason=f"service={service} tag={tag:#x}")
                    continue
                self.evidence.write("task_request", session,
                                    reason=f"service={service} task={task} bytes={len(payload)} "
                                           f"args={decode_typed_fields(payload[3:])}",
                                    body_hex=payload.hex() if len(payload) <= 1024 else None)
                if (service, task) == (71, 4):
                    # LSG_T4_MODE selects the task4 reply shape. "entry" sends a
                    # full 114-byte bdMatchMaking record (same as task9), which
                    # may be what prompts the client to continue with task9;
                    # "zero" is the historical 4-byte empty answer.
                    t4_mode = os.environ.get("LSG_T4_MODE", "zero")
                    if t4_mode == "entry":
                        reply_payload = candidate_svc71_task9_reply(
                            counter, int(os.environ.get("FINDSESS_PORT", "8466")))
                    else:
                        reply_payload = candidate_svc71_task4_reply(counter)
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason="svc71/task4 reference candidate; client consumption unverified")
                    counter += 1
                elif service == 80 and task in (130, 131, 132, 133):
                    # Marketplace getBalance: u8 currency + u32 balance, from the
                    # persisted profile rather than a hardcoded number.
                    profile = self.profile_store.get_or_create(self.user_id)
                    currency = 2
                    if payload[3:]:
                        currency = payload[3] if payload[3] in (1, 2) else 2
                    body = self.profile_store.balance_bytes(profile, currency)
                    reply_payload = (_typed_u64(counter) + _typed_u32(0)
                                     + b"\x03" + bytes([task & 0xFF])
                                     + _typed_u32(1) + _typed_u32(1) + body)
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason=f"svc80/task{task} balance currency={currency} "
                                               f"from profile {profile.get('name')}")
                    counter += 1
                elif service == 255 and task in (60049 & 0xFF, 73):
                    # playerData. The 2-byte task id 60049 arrives truncated to
                    # one byte on this wire format, so 0x91 (60049 & 0xFF) and
                    # 73 are both treated as playerData requests.
                    profile = self.profile_store.get_or_create(self.user_id)
                    body = self.profile_store.playerdata_bytes(profile)
                    reply_payload = (_typed_u64(counter) + _typed_u32(0) + b"\x03"
                                     + bytes([task & 0xFF])
                                     + _typed_u32(1) + _typed_u32(1) + body)
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason=f"svc255/task{task} playerData level="
                                               f"{profile.get('level')} name={profile.get('name')}")
                    counter += 1
                elif (service, task) == (71, 9):
                    # LSG_T9_MODE selects the task9 reply shape. "error14" is
                    # what the M3 run that reached the lobby actually sent (a
                    # 14-byte unimplemented error), and the client continued to
                    # task3 regardless. "entry" sends the 114-byte bdMatchMaking
                    # record, which the client does not yet parse correctly.
                    t9_mode = os.environ.get("LSG_T9_MODE", "error14")
                    if t9_mode == "entry":
                        reply_payload = candidate_svc71_task9_reply(
                            counter, int(os.environ.get("FINDSESS_PORT", "8466")))
                    else:
                        reply_payload = terminal_unavailable_reply(counter)
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason=f"svc71/task9 mode={t9_mode} "
                                               f"bytes={len(reply_payload)}; "
                                               "client consumption unverified")
                    counter += 1
                elif (service, task) == (21, 5) and payload[4:8] == b"\x01\x00\x00\x00":
                    # query1: hand out a game endpoint.  The training and
                    # matchmaking flows ask for it right before "searching for
                    # servers"; the result is the 114-byte bdMatchMaking entry.
                    game_port = int(os.environ.get("GAME_PORT", "8466"))
                    entry = make_server_entry(b"\x7f\x00\x00\x01", game_port)
                    body = (_typed_u64(counter) + _typed_u32(0) + b"\x03" + bytes([task])
                            + _typed_u32(1) + _typed_u32(1) + entry)
                    frame = build_server_frame85(keys, body, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(frame)
                    self.evidence.write("game_alloc_reply", session,
                                        reason=f"svc21/task5 query1 -> 127.0.0.1:{game_port} "
                                               f"entry={len(entry)}B")
                    counter += 1
                elif (service, task) == (21, 13) or (
                        (service, task) == (21, 5) and payload[4:8] in (b"\x04\x00\x00\x00",
                                                                       b"\x05\x00\x00\x00")):
                    # Public room browser (ROOM_BROWSER_PREPARATION.md): 21/13 is
                    # the paged query, 21/5 query=4/5 the plain one. Both answer
                    # with bdMatchMaking room listing records; one record is
                    # smaller than any observed page size, so the client marks
                    # the query finished and renders the row.
                    if os.environ.get("LSG_ROOM_LIST", "1") == "0":
                        self.evidence.write("room_list_suppressed", session,
                                            reason=f"svc{service}/task{task} room list disabled")
                        continue
                    variant = 0
                    label = "baseline"
                    if os.environ.get("ROOM_LIST_CYCLE", "0") == "1":
                        variant = getattr(self, "_room_list_variant", 0)
                        self._room_list_variant = variant + 1
                    room_error = int(os.environ.get("ROOM_ERROR", "0") or 0)
                    if room_error:
                        body = _typed_u64(counter) + _typed_u32(room_error)
                        frame = build_server_frame85(keys, body, counter=received_counter,
                                                     iv=os.urandom(16))
                        conn.sendall(frame)
                        self.evidence.write("room_error_reply", session,
                                            reason=f"svc21/task13 error={room_error}")
                        counter += 1
                        continue
                    delay_ms = int(os.environ.get("ROOM_DELAY_MS", "0") or 0)
                    if delay_ms > 0:
                        time.sleep(delay_ms / 1000.0)
                    if os.environ.get("ROOM_ACK_MODE", "0") == "1":
                        # Send the 0x85 result, then probe 0x84 frames as a
                        # possible task-completion/ack channel.
                        base = room_listing_reply(counter, task_id=task)
                        frame = build_server_frame85(keys, base,
                                                     counter=received_counter,
                                                     iv=os.urandom(16))
                        conn.sendall(frame)
                        acks = [bytes([0x08]) + struct.pack("<I", 9),
                                bytes([0x08]) + struct.pack("<I", 13),
                                bytes([0x06]) + struct.pack("<H", 13)]
                        for payload in acks:
                            ack = build_server_frame85(keys, payload,
                                                       counter=received_counter + 1,
                                                       iv=os.urandom(16),
                                                       frame_type=0x84)
                            conn.sendall(ack)
                            time.sleep(0.2)
                        self.evidence.write("room_ack_probe", session,
                                            reason="0x85 result + 3x 0x84 ack probes")
                        counter += 1
                        continue
                    if os.environ.get("ROOM_ENVELOPE_MATRIX") == "1":
                        rec = make_room_listing_record(
                            room_name=os.environ.get("ROOM_NAME", "AI-Room").encode("latin-1"),
                            channel_id=int(os.environ.get("ROOM_CHANNEL", "1")),
                            port=int(os.environ.get("FINDSESS_PORT", "28969")))
                        frame_counter = received_counter
                        sent = []
                        shapes = []
                        # no-transaction-id shapes first
                        shapes.append(("notid_a", bytes([0x08]) + struct.pack("<I", 0)
                                       + bytes([0x03, task]) + struct.pack("<II", 1, 1) + rec))
                        shapes.append(("notid_b", bytes([0x03, task])
                                       + struct.pack("<II", 1, 1) + rec))
                        shapes.append(("notid_c", bytes([0x08]) + struct.pack("<I", 0)
                                       + bytes([0x03, task]) + struct.pack("<I", 1) + rec))
                        shapes.append(("taskfirst", bytes([0x03, task]) + struct.pack("<Q", counter)
                                       + struct.pack("<II", 1, 1) + rec))
                        for name, body in shapes:
                            frame = build_server_frame85(keys, body, counter=frame_counter,
                                                         iv=os.urandom(16))
                            conn.sendall(frame)
                            frame_counter += 1
                            sent.append(name)
                            time.sleep(0.15)
                        for tid_tag in (0x0A, 0x0B):
                            for err_tag in (0x08, 0x09):
                                for task_tag in (0x03, 0x04):
                                    body = (bytes([tid_tag]) + struct.pack("<Q", counter)
                                            + bytes([err_tag]) + struct.pack("<I", 0)
                                            + bytes([task_tag]) + bytes([task])
                                            + struct.pack("<II", 1, 1) + rec)
                                    frame = build_server_frame85(keys, body,
                                                                 counter=frame_counter,
                                                                 iv=os.urandom(16))
                                    conn.sendall(frame)
                                    frame_counter += 1
                                    sent.append(f"{tid_tag:02x}/{err_tag:02x}/{task_tag:02x}")
                                    time.sleep(0.15)
                        self.evidence.write("room_envelope_matrix", session,
                                            reason="tags=" + ",".join(sent))
                        counter += 1
                        continue
                    if os.environ.get("ROOM_FRAME_MATRIX") == "1":
                        base = room_listing_reply(counter, task_id=task)
                        frame_counter = received_counter
                        combos = [(0x85, 1), (0x85, 0x86), (0x84, 1), (0x85, 0)]
                        for outer, inner in combos:
                            frame = build_server_frame85(keys, base,
                                                         counter=frame_counter,
                                                         iv=os.urandom(16),
                                                         inner_type=inner,
                                                         frame_type=outer)
                            conn.sendall(frame)
                            frame_counter += 1
                            time.sleep(0.2)
                        self.evidence.write("room_frame_matrix", session,
                                            reason="outer/inner=" + ",".join(
                                                f"{o:02x}/{i:02x}" for o, i in combos))
                        counter += 1
                        continue
                    if os.environ.get("ROOM_EMPTY") == "1":
                        empty = room_listing_reply(counter, task_id=task, records=[],
                                                   count_mode="single")
                        frame = build_server_frame85(keys, empty,
                                                     counter=received_counter,
                                                     iv=os.urandom(16))
                        conn.sendall(frame)
                        self.evidence.write("room_empty_reply", session,
                                            reason=f"svc21/task{task} count=0 no total")
                        counter += 1
                        continue
                    records, label = room_list_variant(
                        variant,
                        room_name=os.environ.get("ROOM_NAME", "AI-Room").encode("latin-1"),
                        channel_id=int(os.environ.get("ROOM_CHANNEL", "1")),
                        port=int(os.environ.get("FINDSESS_PORT", "28969")),
                        addr_layout=os.environ.get("ROOM_ADDR_LAYOUT") or None)
                    if os.environ.get("ROOM_HMAC_MODE") == "burst":
                        # One query, several candidate HMAC coverages.  The
                        # client's received-counter check increments per
                        # message, so each candidate needs its own counter.
                        frame_counter = received_counter
                        modes = ("payload", "frame_plain", "frame_plain_padded",
                                 "payload_skip4", "length_payload", "payload_no_tail8")
                        for mode in modes:
                            base = room_listing_reply(counter, task_id=task, records=records)
                            payload = append_message_hmac(base, keys.server_mac, mode)
                            frame = build_server_frame85(keys, payload,
                                                         counter=frame_counter,
                                                         iv=os.urandom(16))
                            conn.sendall(frame)
                            frame_counter += 1
                            time.sleep(0.15)
                        self.evidence.write("room_list_burst", session,
                                            reason="coverage candidates=" + ",".join(modes))
                        counter += 1
                        continue
                    if os.environ.get("ROOM_LAYOUT") == "preamble_burst":
                        # The client's 0xBA3710 parser reads a 4-byte field and
                        # then a 16-byte field before the service envelope, so
                        # A/B a preamble between the length prefix and the inner
                        # byte.  Length coverage is also A/B'd.
                        base = room_listing_reply(counter, task_id=task, records=records)
                        frame_counter = received_counter
                        combos = [(16, "body"), (16, "inner"), (8, "body"),
                                  (8, "inner"), (0, "body")]
                        for plen, covers in combos:
                            iv = os.urandom(16)
                            if plen:
                                frame = build_server_frame85_preamble(
                                    keys, base, counter=frame_counter, iv=iv,
                                    preamble=bytes(plen), length_covers=covers)
                            else:
                                frame = build_server_frame85(keys, base,
                                                             counter=frame_counter, iv=iv)
                            conn.sendall(frame)
                            frame_counter += 1
                            time.sleep(0.2)
                        self.evidence.write("room_layout_burst", session,
                                            reason="layouts=" +
                                                   ",".join(f"pre{plen}/{covers}"
                                                            for plen, covers in combos))
                        counter += 1
                        continue
                    tid_file = os.environ.get("ROOM_TID_FILE")
                    if tid_file and os.path.exists(tid_file):
                        try:
                            counter = int(open(tid_file).read().strip(), 0)
                            self.evidence.write("room_tid_override", session,
                                                reason=f"tid={counter}")
                        except (OSError, ValueError):
                            pass
                    reply_payload = room_listing_reply(
                        counter,
                        task_id=_room_task_id(service, task),
                        records=records,
                        count_mode=os.environ.get("ROOM_COUNT_MODE", "double"),
                        hmac_key=_room_hmac_key(os.environ.get("ROOM_HMAC_MODE", "none"), keys))
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("room_list_reply", session,
                                        reply_hex=reply.hex(),
                                        reason=f"svc{service}/task{task} variant={variant} "
                                               f"{label} records={len(records)} "
                                               f"bytes={len(reply_payload)}")
                    counter += 1
                elif (service, task) == (21, 5):
                    # FindLobbiesByPlaylist. bdsvc319's default variant is one
                    # make_server_entry, the same 114-byte bdMatchMaking record
                    # used for svc71/task9.
                    reply_payload = (candidate_svc71_task9_reply(
                        counter, int(os.environ.get("FINDSESS_PORT", "8466")))
                        .replace(b"\x03\x09", b"\x03\x05", 1))
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_task_reply", session,
                                        reply_hex=reply.hex(),
                                        reason="svc21/task5 one bdMatchMaking entry "
                                               "127.0.0.1:%s; client consumption unverified"
                                               % os.environ.get("FINDSESS_PORT", "8466"))
                    counter += 1
                elif (service, task) == (28, 4):
                    # Presence query.  It used to be left unanswered, but the
                    # client pops one pending task per received kind=0x86
                    # message, so silence here made every later reply land on
                    # the wrong task.  Reply with a terminal failure instead.
                    reply = build_server_frame85(
                        keys, terminal_unavailable_reply(counter),
                        counter=received_counter, iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("terminal_task_reply", session,
                                        reason=f"service={service} task={task} error=4 "
                                               "in-order failure (presence not implemented)")
                    counter += 1
                elif (service, task) in ((11, 13), (71, 3), (71, 7), (102, 5)):
                    # LSG_UNIMPL_MODE picks the reply for services we do not
                    # implement. The M3 run that reached the lobby answered these
                    # with terminal_task_reply error=14 and the client kept going,
                    # so error14 is the default; empty is kept for comparison.
                    unimpl = os.environ.get("LSG_UNIMPL_MODE", "error14")
                    if unimpl == "empty":
                        reply_payload = candidate_empty_success_reply(counter, task)
                    else:
                        reply_payload = terminal_unavailable_reply(counter)
                    reply = build_server_frame85(keys, reply_payload, counter=received_counter,
                                                 iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_empty_task_reply", session,
                                        reason=f"service={service} task={task} mode={unimpl}; "
                                               "shape unverified")
                    counter += 1
                elif self.observed71_empty and service == 71 and task in (3, 7, 9):
                    reply = build_server_frame85(
                        keys, candidate_empty_success_reply(counter, task),
                        counter=received_counter, iv=os.urandom(16))
                    conn.sendall(reply)
                    self.evidence.write("candidate_empty_task_reply", session,
                                        reason=f"service=71 task={task}; 1604220 fallback "
                                               "shape; 1649370 consumption unverified")
                    counter += 1
                else:
                    self.evidence.write("unhandled_task", session,
                                        reason=f"service={service} task={task}")
                    if os.environ.get("LSG_UNIMPL_MODE", "error4") == "empty":
                        reply = build_server_frame85(
                            keys, candidate_empty_success_reply(counter, task),
                            counter=received_counter, iv=os.urandom(16))
                        conn.sendall(reply)
                        self.evidence.write("candidate_empty_task_reply", session,
                                            reason=f"service={service} task={task} "
                                                   "empty success; consumption unverified")
                    else:
                        reply = build_server_frame85(
                            keys, terminal_unavailable_reply(counter),
                            counter=received_counter, iv=os.urandom(16))
                        conn.sendall(reply)
                        self.evidence.write("terminal_task_reply", session,
                                            reason=f"service={service} task={task} error=4; "
                                                   "candidate contract, consumption unverified")
                    counter += 1
        except (LsgProtocolError, EOFError, OSError, TimeoutError) as exc:
            self.evidence.write("raw_session_end", session,
                                reason=f"{type(exc).__name__}:{exc}")
        finally:
            try:
                conn.close()
            except OSError:
                pass
