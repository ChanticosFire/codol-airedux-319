"""Decode Build 1649370 client packets without executing their commands.

SPDX-License-Identifier: AGPL-3.0-or-later

The interleaved byte/bit reader and usercmd field order follow the community
reference at ``他人文件参考/CODOL-Member-Preview-20261026/native-engine/source/
src/codol/{net/codol_msg.c,player/codol_usercmd.c}`` (AGPL-3.0-or-later).
The packet envelope and key were checked against r762-r764 real client logs.

This module deliberately returns wire input.  It does not infer gameplay
movement, weapon IDs or authority from the command fields.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace


class ClientInputDecodeError(ValueError):
    """A packet did not match the observed 1649370 usermove framing."""


class InterleavedReader:
    def __init__(self, data: bytes):
        self.data = data
        self.cursor = 0
        self.bit = 0

    def raw(self, size: int) -> bytes:
        if size < 0 or self.cursor + size > len(self.data):
            raise ClientInputDecodeError("truncated byte field")
        result = self.data[self.cursor:self.cursor + size]
        self.cursor += size
        return result

    def byte(self) -> int:
        return self.raw(1)[0]

    def short(self) -> int:
        return struct.unpack("<H", self.raw(2))[0]

    def long(self) -> int:
        return struct.unpack("<I", self.raw(4))[0]

    def bits(self, width: int) -> int:
        if not 0 <= width <= 32:
            raise ClientInputDecodeError("invalid bit width")
        result = 0
        for index in range(width):
            if not (self.bit & 7):
                if self.cursor >= len(self.data):
                    raise ClientInputDecodeError("truncated bit pool")
                self.bit = self.cursor * 8
                self.cursor += 1
            result |= ((self.data[self.bit // 8] >> (self.bit & 7)) & 1) << index
            self.bit += 1
        return result

    def string(self, limit: int = 2048) -> bytes:
        end = self.data.find(b"\0", self.cursor)
        if end < 0 or end - self.cursor > limit:
            raise ClientInputDecodeError("unterminated client command")
        result = self.data[self.cursor:end]
        self.cursor = end + 1
        return result


@dataclass(frozen=True)
class UserCmd:
    server_time: int = 0
    buttons: int = 0
    angles: tuple[int, int, int] = (0, 0, 0)
    direction: int = 0
    weapon: int = 0
    offhand: int = 0
    alt_weapon: int = 0
    selected_location: tuple[int, int] = (0, 0)
    selected_location_angle: int = 0
    remote_angles: tuple[int, int] = (0, 0)
    melee_yaw: int = 0
    melee_dist: int = 0
    melee_entity: int = 0


@dataclass(frozen=True)
class ClientInput:
    sequence: int
    server_id: int
    message_ack: int
    reliable_ack: int
    client_commands: tuple[tuple[int, bytes], ...]
    move_opcode: int
    usercmds: tuple[UserCmd, ...]
    reported_origin: tuple[float, float, float]
    origin_time: int
    client_word: int


def _delta_bits(reader: InterleavedReader, key: int, old: int, width: int) -> int:
    return (reader.bits(width) ^ (key & ((1 << width) - 1))) if reader.bits(1) else old


def _delta_short(reader: InterleavedReader, key: int, old: int) -> int:
    return ((reader.short() ^ key) & 0xFFFF) if reader.bits(1) else old


def _delta_byte(reader: InterleavedReader, key: int, old: int) -> int:
    return ((reader.byte() ^ key) & 0xFF) if reader.bits(1) else old


def _read_usercmd(reader: InterleavedReader, key: int, old: UserCmd) -> UserCmd:
    stamp = ((old.server_time + reader.byte()) & 0xFFFFFFFF
             if reader.bits(1) else reader.long())
    cmd = replace(old, server_time=stamp)
    tag = 7
    if reader.bits(1) ^ (key & 1):
        if not (reader.bits(1) ^ (key & 1)):
            tag = 2
            derived = key ^ stamp
            buttons = (old.buttons & ~1) | (reader.bits(1) ^ (derived & 1))
            a0 = _delta_short(reader, derived, old.angles[0])
            a1 = _delta_short(reader, derived, old.angles[1])
            direction = _delta_bits(reader, derived, old.direction, 4)
            cmd = replace(cmd, buttons=buttons,
                          angles=(a0, a1, old.angles[2]), direction=direction)
        else:
            tag = 5
            fire = reader.bits(1) ^ (key & 1)
            a0 = _delta_short(reader, key, old.angles[0])
            a1 = _delta_short(reader, key, old.angles[1])
            direction = _delta_bits(reader, key, old.direction, 4)
            derived = key ^ stamp
            a2 = _delta_short(reader, derived, old.angles[2])
            upper = _delta_bits(reader, derived, old.buttons >> 1, 29)
            buttons = upper * 2 | fire
            weapon = _delta_bits(reader, derived, old.weapon, 11)
            offhand = _delta_bits(reader, derived, old.offhand, 11)
            alt_weapon = _delta_bits(reader, derived, old.alt_weapon, 11)
            cmd = replace(cmd, buttons=buttons, angles=(a0, a1, a2),
                          direction=direction, weapon=weapon,
                          offhand=offhand, alt_weapon=alt_weapon)
            if buttons & 0x20000:
                selected = (_delta_byte(reader, derived, old.selected_location[0]),
                            _delta_byte(reader, derived, old.selected_location[1]))
                angle = _delta_byte(reader, derived, old.selected_location_angle)
                cmd = replace(cmd, selected_location=selected,
                              selected_location_angle=angle)
            if buttons & 0x200000:
                remote = (_delta_byte(reader, derived, old.remote_angles[0]),
                          _delta_byte(reader, derived, old.remote_angles[1]))
                cmd = replace(cmd, remote_angles=remote)
            if buttons & 4:
                yaw = _delta_short(reader, derived, old.melee_yaw)
                dist = _delta_bits(reader, derived, old.melee_dist, 8)
                entity = _delta_bits(reader, derived, old.melee_entity, 11)
                cmd = replace(cmd, melee_yaw=yaw, melee_dist=dist,
                              melee_entity=entity)
    actual = reader.bits(3)
    if actual != tag:
        raise ClientInputDecodeError(f"usercmd tag {actual} expected {tag}")
    return cmd


def _xor_body(data: bytes, seed: int, reliable_command: bytes) -> bytes:
    key = seed & 0xFF
    index = 0
    output = bytearray()
    for offset, value in enumerate(data):
        if reliable_command:
            if index >= len(reliable_command) or not reliable_command[index]:
                index = 0
            key ^= (reliable_command[index] << (offset & 1)) & 0xFF
            index += 1
        output.append(value ^ key)
    return bytes(output)


def _usercmd_key(ack: int, checksum_feed: int, reliable_command: bytes) -> int:
    hashed = 0
    for index, value in enumerate(reliable_command[:32].split(b"\0", 1)[0]):
        signed = value if value < 128 else value - 256
        hashed = (hashed + signed * (119 + index)) & 0xFFFFFFFF
    signed_hash = hashed if hashed < 0x80000000 else hashed - 0x100000000
    return (ack ^ checksum_feed ^ hashed ^ (signed_hash >> 10)
            ^ (signed_hash >> 20)) & 0xFFFFFFFF


def decode_client_packet(packet: bytes, *, challenge: int, checksum_feed: int,
                         reliable_command: bytes = b"",
                         baseline: UserCmd = UserCmd()) -> ClientInput:
    """Validate and decode one complete client datagram; reject fragments.

    The caller must supply the checksum feed from the actual gamestate and the
    reliable command acknowledged by this packet.  The r738 match uses both
    values as zero/empty.  A default baseline decodes observed direction and
    attack transitions; other unchanged weapon fields need exact snapshot
    history before they can be used as authoritative gameplay data.
    """
    if len(packet) < 15:
        raise ClientInputDecodeError("short client packet")
    sequence = struct.unpack_from("<I", packet)[0]
    if sequence & 0x80000000:
        raise ClientInputDecodeError("fragment requires reassembly")
    server_id = packet[4]
    message_ack = struct.unpack_from("<I", packet, 5)[0]
    reliable_ack = struct.unpack_from("<I", packet, 9)[0]
    if message_ack & 0x80000000:
        raise ClientInputDecodeError("negative message ACK")
    if reliable_ack and not reliable_command:
        raise ClientInputDecodeError("missing acknowledged reliable command")
    seed = challenge ^ server_id ^ message_ack
    plaintext = _xor_body(packet[13:], seed, reliable_command)
    reader = InterleavedReader(plaintext)
    commands: list[tuple[int, bytes]] = []
    for _ in range(512):
        opcode = reader.bits(3)
        if opcode == 2:
            commands.append((reader.long(), reader.string()))
            continue
        if opcode == 4:
            continue
        if opcode not in (0, 1):
            raise ClientInputDecodeError(f"unexpected client opcode {opcode}")
        count = reader.byte()
        if not 1 <= count <= 32:
            raise ClientInputDecodeError(f"invalid usercmd count {count}")
        key = _usercmd_key(message_ack, checksum_feed, reliable_command)
        prior = baseline
        usercmds: list[UserCmd] = []
        for _ in range(count):
            prior = _read_usercmd(reader, key, prior)
            usercmds.append(prior)
        origin = tuple(struct.unpack("<f", struct.pack("<I", reader.long()))[0]
                       for _ in range(3))
        origin_time = reader.long()
        client_word = reader.long()
        if not all(math.isfinite(value) for value in origin):
            raise ClientInputDecodeError("nonfinite client origin")
        if reader.bits(3) != 3 or reader.cursor != len(plaintext):
            raise ClientInputDecodeError("missing final EOF or trailing data")
        return ClientInput(sequence, server_id, message_ack, reliable_ack,
                           tuple(commands), opcode, tuple(usercmds), origin,
                           origin_time, client_word)
    raise ClientInputDecodeError("too many client commands")
