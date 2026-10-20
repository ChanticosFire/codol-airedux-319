"""Build 1649370 LSG CLI and retained legacy memory-reading probe.

The default CLI uses :mod:`server319.lsg_derived`, whose handshake derivation
has been replayed against three target-Build raw captures. ``LsgServer`` below
is retained only for explicit ``--legacy-probe`` comparison; its responses were
diagnostic experiments and did not establish a usable lobby.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

from .auth import AuthEvidence, AuthServer, parse_request

LSG_NOT_IMPLEMENTED = b'{"error":"lsg-not-implemented"}'
LSG_MARK = 0x1122334455667788  # reference handshake mark (lsg_echo319)

# 26-byte gate reply observed in the reference: [u32 22][01][81][u32 0xD2][8B mark][8B nonce]
LSG_GATE_OP = 0x81
LSG_GATE_VALUE = 0xDC  # 220: 0xBA3AEB requires [conn+0x640] >= 220


class LsgServer(AuthServer):
    """Same TLS/HTTP plumbing as Auth, but a lobby-shaped response."""

    def _handle(self, conn: socket.socket) -> None:
        session = self._new_session()
        try:
            head = conn.recv(16, socket.MSG_PEEK)
        except OSError:
            head = b""
        if head and head[0] not in (0x16, 0x80):
            self.evidence.write("plaintext_connect", session, client=str(conn.getpeername()[0]),
                                request_line=f"first_byte=0x{head[0]:02x}")
            try:
                conn.settimeout(5)
                data = conn.recv(4096)
                if data:
                    self.evidence.write("plaintext_frame", session, body_len=len(data),
                                        body_sha256=hashlib.sha256(data).hexdigest(),
                                        body_hex=data[:256].hex())
                    # Answer the 28-byte hello with the 26-byte gate frame so the
                    # client advances to its 0x82 challenge instead of timing out.
                    nonce = os.urandom(8)
                    reply = (bytes([0x01, LSG_GATE_OP])
                             + struct.pack("<I", LSG_GATE_VALUE)
                             + struct.pack("<Q", LSG_MARK) + nonce)
                    frame = struct.pack("<I", len(reply)) + reply
                    conn.sendall(frame)
                    self.evidence.write("gate_reply", session, reply_hex=frame.hex())
                    try:
                        conn.settimeout(8)
                        more = conn.recv(4096)
                        if more:
                            self.evidence.write("plaintext_frame2", session, body_len=len(more),
                                                body_sha256=hashlib.sha256(more).hexdigest(),
                                                body_hex=more[:256].hex())
                            # The client compares our 0x83 token against its own
                            # conn+0x5FC, so read that field out of the game.
                            try:
                                from . import lsg_client
                                pid, caddr, challenge = 0, 0, None
                                candidates = []
                                for candidate_pid in lsg_client.find_client_pids():
                                    candidates = lsg_client.find_service_conns(candidate_pid)
                                    if not candidates:
                                        candidates = lsg_client.find_conn_by_vtable(candidate_pid)
                                    if not candidates:
                                        candidates = lsg_client.find_conn_candidates(
                                            candidate_pid, LSG_MARK)
                                    if candidates:
                                        pid = candidate_pid
                                        break
                                if candidates:
                                    good = [c for c in candidates if c.get("stage") in (1, 2, 3)]
                                    pick = good[0] if good else candidates[0]
                                    caddr = pick["conn"]
                                    raw = bytes.fromhex(pick["challenge"])
                                    challenge = raw if len(raw) == 8 else None
                                    detail = [{"conn": hex(c["conn"]), "stage": c.get("stage"),
                                               "challenge": c.get("challenge")} for c in candidates[:4]]
                                    self.evidence.write("challenge_detail", session,
                                                        reason=json.dumps(detail)[:600])
                                    if caddr:
                                        around = lsg_client.read_region(pid, caddr + 0x5E0, 0x30)
                                        self.evidence.write("conn_mem", session,
                                                            reason=f"{caddr:#x}+0x5E0 {around}")
                                self.evidence.write(
                                    "challenge_lookup", session,
                                    reason=f"pid={pid} candidates={len(candidates)} conn={caddr:#x}")
                                # Reference self-check: CHAL[:8] == reply[-8:].
                                # Searching the client for that tail reveals the
                                # surrounding 16 bytes, i.e. the real CHAL and the
                                # CHAL[8:16] half our 0x83 must carry.
                                try:
                                    if pid:
                                        # Locate the bdAuthTicket we issued (magic 0xEFBDADDE) and
                                        # read its bytes so the real session_key offset is known.
                                        try:
                                            _hits = lsg_client.search_bytes(
                                                pid, b"\xde\xad\xbd\xef", limit=3, context=160)
                                            self.evidence.write(
                                                "ticket_search", session,
                                                reason=json.dumps([
                                                    {"hit": hex(h["hit"])}
                                                    for h in _hits])[:600])
                                            # The heap copy is the ticket the client kept; read the
                                            # 24-byte session-key field at several candidate offsets.
                                            for _h in _hits:
                                                for _off in (97, 104, 40 + 64):
                                                    _k24 = _lc.read_region(pid, _h["hit"] + _off, 24)
                                                    self.evidence.write(
                                                        "ticket_key", session,
                                                        reason=f"hit={_h['hit']:#x} off={_off} key={_k24}")
                                        except Exception as _exc:
                                            self.evidence.write("ticket_search_error", session,
                                                                reason=type(_exc).__name__)
                                    if pid:
                                        # codol-node reads the fixed session key at 0x111F440;
                                        # confirm the same address on 1649370.
                                        try:
                                            _sk = lsg_client.read_region(pid, 0x111F440, 24)
                                            self.evidence.write("session_key_probe", session,
                                                                reason=f"0x111F440={_sk}")
                                            # Is the codol-node SESSION_KEY actually present in
                                            # this build's memory somewhere else?
                                            _needle = bytes.fromhex(
                                                "8ecd56428021ead23643c94801f4095daafe3875f087b13f")
                                            _skhits = lsg_client.search_bytes(pid, _needle,
                                                                              limit=3, context=4)
                                            self.evidence.write(
                                                "session_key_search", session,
                                                reason=json.dumps([hex(h["hit"]) for h in _skhits]))
                                        except Exception as _exc:
                                            self.evidence.write("session_key_probe", session,
                                                                reason=type(_exc).__name__)
                                    if pid and len(more) >= 8:
                                        tail8 = more[-8:]
                                        found = lsg_client.search_bytes(pid, tail8, limit=4,
                                                                        context=32)
                                        self.evidence.write(
                                            "chal_search", session,
                                            body_hex=tail8.hex(),
                                            reason=json.dumps([
                                                {"hit": hex(h["hit"]), "around": h["around"]}
                                                for h in found])[:900])
                                except Exception as _exc:
                                    self.evidence.write("chal_search_error", session,
                                                        reason=type(_exc).__name__)
                            except Exception as exc:  # keep the listener alive
                                pid, caddr, challenge = 0, 0, None
                                self.evidence.write("challenge_error", session,
                                                    reason=type(exc).__name__)
                            self.evidence.write("challenge_choice", session,
                                                reason=f"token={challenge.hex() if challenge else None}")
                            if challenge:
                                reply83 = b"\x00\x83" + challenge
                                frame83 = struct.pack("<I", len(reply83)) + reply83
                                conn.sendall(frame83)
                                self.evidence.write("token_reply", session,
                                                    reply_hex=frame83.hex())
                                # 0xBA3AEB: only a type-0x87 frame (with conn+0x640 >= 220)
                                # reaches 0xBA3590, which builds the crypt channel and sets
                                # [conn+0x644]=1. Without it crypt stays 0 and 0xBA0780 can
                                # never return 2, so ui_state never reaches 5.
                                # 0xBA3ABB: the u32 length field is added to the post-type
                                # offset (5), so it must count only the payload bytes.
                                # 0xBA308E reads tag 1 with a 136-byte payload via 0xB75DE0,
                                # so the 0x87 body must actually carry that much data.
                                # 0xBA3590 checks byte0==1, then 0xBA3010 reads tag 1 with a
                                # 0x88-byte payload via 0xB75DE0, so encode tag+len+data.
                                f87_body = b"\x01" + b"\x88" + b"\x00" * 136
                                f87 = (struct.pack("<I", len(f87_body))
                                       + b"\x87" + f87_body)
                                # 0xBA2B5D: while crypt==0 the receiver requires
                                # lstate==2 && stage==3, and stage only reaches 3 a few
                                # seconds after 0x83, so delay the 0x87 frame.
                                # PROGRESS.md: svc28 must stay silent; pushing unsolicited
                                # frames (0x87) only accelerates the disconnect.

                                self.evidence.write("frame87", session, reply_hex=f87.hex())
                                # Keep reading: the client may answer with the
                                # 0x85 encrypted channel frame right after.
                                try:
                                    conn.settimeout(10)
                                    after = conn.recv(8192)
                                    if after:
                                        self.evidence.write("plaintext_frame3", session,
                                                            body_len=len(after),
                                                            body_sha256=hashlib.sha256(after).hexdigest(),
                                                            body_hex=after[:512].hex())
                                        # 0x85 carries the AES channel: conn+0x604/0x608
                                        # hold POINTERS; the 16-byte key lives at [ptr+0x9C].
                                        # 0x604 decrypts the client's frames (verified:
                                        # it yields the 84-byte 0x86 login request);
                                        # 0x608 encrypts our replies.
                                        try:
                                            from Crypto.Cipher import AES
                                            from . import lsg_client as _lc
                                            _pids = _lc.find_client_pids()
                                            if not _pids:
                                                raise RuntimeError("no-client")
                                            _pid = _pids[0]
                                            _ks = _lc.read_u32(_pid, caddr + 0x604)
                                            _kr = _lc.read_u32(_pid, caddr + 0x608)
                                            if not _ks or not _kr:
                                                raise RuntimeError("no-key-ptr")
                                            key_send = bytes.fromhex(_lc.read_region(_pid, _ks + 0x9C, 16))
                                            object_key_recv = bytes.fromhex(
                                                _lc.read_region(_pid, _kr + 0x9C, 16))
                                            key_recv = object_key_recv
                                            # Optional legacy diagnostic override, never the
                                            # default: five same-build captures match the derived
                                            # S2C AES key at [conn+0x608]+0x9C.
                                            if "LSG_KEYOFF" in os.environ:
                                                _koff = int(os.environ["LSG_KEYOFF"], 0)
                                                _cand = _lc.read_region(_pid, _ks + _koff, 16)
                                                if len(_cand) == 32:
                                                    key_recv = bytes.fromhex(_cand)
                                            # Hunt for every AES object reachable from the conn:
                                            # the C2S object is at conn+0x604 (vtable 0x2055D900);
                                            # a sibling field should hold the S2C object.
                                            _found = []
                                            for _off in range(0x5F0, 0x660, 4):
                                                _p = _lc.read_u32(_pid, caddr + _off)
                                                if not _p or _p < 0x10000:
                                                    continue
                                                _vt = _lc.read_u32(_pid, _p)
                                                if _vt == 0x2055D900:
                                                    _blk = _lc.read_region(_pid, _p, 0x40)
                                                    _tail2 = _lc.read_region(_pid, _p + 0x80, 0x40)
                                                    _found.append({"off": hex(_off), "ptr": hex(_p),
                                                                   "head": _blk, "tail": _tail2})
                                            self.evidence.write("aes_objects", session,
                                                                reason=json.dumps(_found)[:1500])
                                            # Identify what these two objects actually are.
                                            for _lbl, _ptr, _key in (("604", _ks, key_send),
                                                                     ("608", _kr, object_key_recv)):
                                                _head = _lc.read_region(_pid, _ptr, 0x40)
                                                _tail = _lc.read_region(_pid, _ptr + 0x80, 0x40)
                                                self.evidence.write(
                                                    "key_object", session,
                                                    reason=f"{_lbl} ptr={_ptr:#x} key={_key.hex()} "
                                                           f"head={_head} tail={_tail}")
                                            _silent = os.environ.get("LSG_SILENT_AFTER83") == "1"
                                            if after[:6][4:6] == b"\xab\x85" and not _silent:
                                                seq = after[6:10]
                                                iv = after[10:26]
                                                cipher = after[26:-8]
                                                # stage only reaches 3 after the client has sent
                                                # its 0x85, so the 0x87 push must happen here.
                                                _deadline = time.time() + float(
                                                    os.environ.get("LSG_F87_WAIT", "25"))
                                                while time.time() < _deadline:
                                                    if _lc.read_u32(_pid, caddr + 0x5E8) == 3:
                                                        break
                                                    time.sleep(0.4)
                                                self.evidence.write(
                                                    "f87_ready", session,
                                                    reason="stage=" + str(
                                                        _lc.read_u32(_pid, caddr + 0x5E8)))
                                                conn.sendall(f87)
                                                pt = AES.new(key_send, AES.MODE_CBC, iv=iv).decrypt(cipher)
                                                self.evidence.write("frame85_plain", session,
                                                                    body_hex=pt.hex())
                                                # Experiment: echo the client's own request as
                                                # the heartbeat payload (lsg_echo319 uses an
                                                # externally supplied pt; echo is the safest probe).
                                                echo_pt = pt + b"\x00" * ((-len(pt)) % 16)
                                                # Reference evt4 (1604220 lobby.py):
                                                #   emit_inner(4, BB_UINT64_TYPE + u64(1))
                                                #   IV is the fixed bytes(range(16,32)), not random.
                                                # Keepalive is NOT an encrypted frame: pump() sends a
                                                # bare 4-byte zero every 20s and skips received zeros.
                                                # 1649370 accepts inner 0x88 with a business type
                                                # 4 payload carrying tag 0x0A; the reference's
                                                # inner 4 + connId variant makes 1649370 close the
                                                # socket immediately.
                                                # P3 gate (zero-patch analysis): the lobby needs the
                                                # svc80/task230 playerdata answer, shaped like the
                                                # reference task_reply with inner type 1:
                                                #   u64 txn | u32 err | u8 task | u32 nres | u32 nres
                                                #   | level | prestige | gp | cp | n_ent | n_flags
                                                bd = ((1).to_bytes(8, "little")
                                                      + (0).to_bytes(4, "little")
                                                      + bytes([230])
                                                      + (1).to_bytes(4, "little")
                                                      + (1).to_bytes(4, "little"))
                                                bd += (70).to_bytes(4, "little")
                                                bd += (0).to_bytes(4, "little")
                                                bd += (999999999).to_bytes(4, "little")
                                                bd += (999999999).to_bytes(4, "little")
                                                bd += (0).to_bytes(2, "little")
                                                bd += (0).to_bytes(2, "little")
                                                inner = b"\x01" + bd
                                                evt4_pt = struct.pack("<I", len(inner)) + inner
                                                evt4_pt += b"\x00" * ((-len(evt4_pt)) % 16)
                                                # 1649370 does NOT keep the rx counter at conn+0x5EC
                                                # (that offset holds lobby-name text); echo the
                                                # sequence the client itself used in its 0x85.
                                                _rxseq = int.from_bytes(seq, "little")
                                                fixed_iv = os.urandom(16)  # 1649370 takes the IV from the frame
                                                if os.environ.get("LSG_PLAIN85") == "1":
                                                    # PROGRESS.md shows plaintext business frames on
                                                    # this build; try an unencrypted 0x85 reply.
                                                    _rct = evt4_pt
                                                else:
                                                    _rct = AES.new(key_recv, AES.MODE_CBC,
                                                                   iv=fixed_iv).encrypt(evt4_pt)
                                                if os.environ.get("LSG_PLAIN85") == "1":
                                                    _evt4 = (b"\x01\x85" + struct.pack("<I", _rxseq)
                                                             + _rct)
                                                else:
                                                    _evt4 = (b"\x01\x85" + struct.pack("<I", _rxseq)
                                                             + fixed_iv + _rct + b"\x00" * 8)
                                                conn.sendall(struct.pack("<I", len(_evt4)) + _evt4)
                                                # Did the client actually decrypt our frame? Search for
                                                # our plaintext head and our ciphertext head.
                                                try:
                                                    for _label, _needle in (("pt", evt4_pt[:12]),
                                                                            ("ct", _rct[:12])):
                                                        _hits = _lc.search_bytes(_pid, _needle, limit=2,
                                                                                 context=16)
                                                        self.evidence.write(
                                                            "frame85_seen", session,
                                                            body_hex=_needle.hex(),
                                                            reason=_label + " " + json.dumps(
                                                                [hex(h["hit"]) for h in _hits]))
                                                except Exception as _exc:
                                                    self.evidence.write("frame85_seen_error", session,
                                                                        reason=type(_exc).__name__)
                                                self.evidence.write("frame85_reply", session,
                                                                    body_hex=evt4_pt.hex(),
                                                                    reply_hex=_evt4.hex(),
                                                                    reason="evt4-inner04-tag0a")
                                                # Silent keepalive window: 4-byte zero frames every 20s,
                                                # answering any client 0x85 along the way.
                                                try:
                                                    conn.settimeout(0.5)
                                                    _end = time.time() + 90.0
                                                    _next_ka = time.time() + 30.0
                                                    while time.time() < _end:
                                                        try:
                                                            _more = conn.recv(8192)
                                                        except socket.timeout:
                                                            _more = None
                                                        except OSError:
                                                            break
                                                        if _more is None:
                                                            if time.time() >= _next_ka:
                                                                conn.sendall(b"\x00\x00\x00\x00")
                                                                self.evidence.write(
                                                                    "keepalive", session,
                                                                    reason="4-zero")
                                                                _next_ka = time.time() + 30.0
                                                            continue
                                                        if not _more:
                                                            self.evidence.write("peer_closed", session)
                                                            break
                                                        if _more == b"\x00\x00\x00\x00":
                                                            self.evidence.write("idle_control", session)
                                                            continue
                                                        self.evidence.write(
                                                            "plaintext_frame4", session,
                                                            body_len=len(_more),
                                                            body_sha256=hashlib.sha256(_more).hexdigest(),
                                                            body_hex=_more[:512].hex())
                                                        if len(_more) > 26 and _more[4:6] == b"\xab\x85":
                                                            _iv = _more[10:26]
                                                            _ct = _more[26:-8]
                                                            _pt = AES.new(key_send, AES.MODE_CBC,
                                                                          iv=_iv).decrypt(_ct)
                                                            self.evidence.write("frame85_in", session,
                                                                                body_hex=_pt.hex())
                                                            _ria = os.urandom(16)
                                                            _rcb = AES.new(key_send, AES.MODE_CBC,
                                                                           iv=_ria).encrypt(
                                                                               struct.pack("<I", 1)
                                                                               + b"\x01")
                                                            _ans = (b"\x01\x85" + struct.pack("<I", _rxseq)
                                                                    + _ria + _rcb + b"\x00" * 8)
                                                            conn.sendall(
                                                                struct.pack("<I", len(_ans)) + _ans)
                                                            self.evidence.write("frame85_answer", session,
                                                                                reply_hex=_ans.hex())
                                                except OSError:
                                                    pass
                                        except Exception as _exc:
                                            self.evidence.write("key_error", session,
                                                                reason=type(_exc).__name__)
                                except OSError:
                                    pass
                    except OSError:
                        pass
            except OSError:
                pass
            finally:
                conn.close()
            return
        try:
            tls = self.context.wrap_socket(conn, server_side=True)
        except Exception as exc:
            self.evidence.write("tls_handshake_failed", session, reason=type(exc).__name__)
            conn.close()
            return
        try:
            raw = b""
            tls.settimeout(12)
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
            length = int(headers.get("content-length") or 0)
            body = rest
            if headers.get("expect", "").lower() == "100-continue":
                tls.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            while len(body) < length:
                chunk = tls.recv(65536)
                if not chunk:
                    break
                body += chunk
            body = body[:length] if length else body
            session.requests += 1
            self.evidence.write("lsg_request", session, request_line=lines[0],
                                headers=lines[1:40], body_len=len(body),
                                body_sha256=hashlib.sha256(body).hexdigest())
            response = (
                b"HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(LSG_NOT_IMPLEMENTED)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + LSG_NOT_IMPLEMENTED
            )
            tls.sendall(response)
            self.evidence.write("lsg_response", session, status=404, response_len=len(response))
        except Exception as exc:
            self.evidence.write("io_error", session, reason=type(exc).__name__)
        finally:
            try:
                tls.close()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build 1649370 LSG responder")
    parser.add_argument("--cert", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--client-dir", type=Path,
                        default=Path("runtime/client-1649370"),
                        help="isolated Build 1649370 copy for four-anchor preflight")
    parser.add_argument("--legacy-probe", action="store_true",
                        help="use the prior memory-reading diagnostic handler")
    parser.add_argument("--token-marker", choices=("00", "ab"), default="00",
                        help="0x83 wire marker; 00 preserves the observed local baseline")
    args = parser.parse_args(argv)
    from .manifest import verify_client
    checks = verify_client(args.client_dir)
    if not all(check.ok for check in checks):
        parser.error("client identity mismatch: " + ", ".join(
            check.path for check in checks if not check.ok))
    if args.legacy_probe:
        server = LsgServer(args.port, args.cert, args.key, AuthEvidence(args.log))
    else:
        from .lsg_derived import DerivedLsgServer
        server = DerivedLsgServer(args.port, args.cert, args.key,
                                  AuthEvidence(args.log),
                                  token_marker=int(args.token_marker, 16))
    server.start()
    print(f"LSG {'legacy probe' if args.legacy_probe else 'derived'} listening "
          f"127.0.0.1:{args.port} for {args.seconds:g}s", flush=True)
    try:
        server.serve(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
