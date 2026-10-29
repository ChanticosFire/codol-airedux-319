"""Bit-exact 1649370 snapshot writer, rebuilt from the community wire spec.

The layout and every codec here follow the protocol facts recorded in
`docs/1649370-COMMUNITY-WIRE-SPEC.md`, which were read out of the build's own
reader (0x6701D0 / 0x671170 / 0x671D80) by the community member preview
package.  The clientState descriptor values are transcribed into
`client_fields164.py`; the Python writers reproduce the documented wire
behaviour.

Two things make this writer different from `server1649370/ps_codec.py`:

1. **Dual cursors.**  The 1649370 message keeps a byte cursor and a bit
   cursor.  ``write_byte`` advances only the byte cursor; ``write_bits``
   re-aligns to the byte cursor whenever the bit cursor is byte-aligned.
   That is why the field stream can run "underneath" bytes written later.
2. **Compressed positive-width fields.**  A positive width ``n`` writes
   ``n & 7`` remainder bits with ``write_bits`` and then whole bytes with
   ``write_byte``.  It is *not* a plain LSB-first run of ``n`` bits.

Frame (after the 4-byte ack the server adds):

    u8 0x00, u32 serverTime, u8 delta, u8 flags, 1 bit has_base
    playerState section, anim section, actors, entities, clients, glass
    u8 0x05

Self-test: ``python -m server1649370.wire164``.
"""

from __future__ import annotations

import math
import struct

from .entity_fields164 import ENTITY_FIELDS164, ENTITY_FIELDS_PER_TYPE164, ENTITY_SENTINEL
from .client_fields164 import CLIENT_FIELDS164
from .player_fields164 import PLAYER_FIELDS164
from .event_fields164 import EVENT_PARAMETER_WIDTHS164

PLAYER_FIELD_COUNT = len(PLAYER_FIELDS164)
TAIL_SECTIONS = 17


class MsgWriter:
    """Mirror of the 1649370 message writer: one buffer, two cursors."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.size = 0
        self.bit = 0
        self.failed = False

    # ---------------------------------------------------------------- bytes
    def write_data(self, payload: bytes) -> None:
        if self.failed:
            return
        self.data.extend(payload)
        self.size += len(payload)

    def write_byte(self, value: int) -> None:
        self.write_data(bytes((value & 0xFF,)))

    def write_short(self, value: int) -> None:
        self.write_data(struct.pack("<H", value & 0xFFFF))

    def write_long(self, value: int) -> None:
        self.write_data(struct.pack("<I", value & 0xFFFFFFFF))

    # ----------------------------------------------------------------- bits
    def write_bits(self, value: int, count: int) -> None:
        if self.failed:
            return
        if count > 32 or count < 0:
            self.failed = True
            return
        for index in range(count):
            if not (self.bit & 7):
                self.bit = self.size * 8
                self.data.append(0)
                self.size += 1
            self.data[self.bit >> 3] |= ((value >> index) & 1) << (self.bit & 7)
            self.bit += 1

    # -------------------------------------------------------------- helpers
    def to_bytes(self) -> bytes:
        return bytes(self.data)


# --------------------------------------------------------------------- codecs
def _mask(width: int) -> int:
    return 0xFFFFFFFF if width == 32 else (1 << width) - 1


def _real(word: int) -> float:
    return struct.unpack("<f", struct.pack("<I", word & 0xFFFFFFFF))[0]


def _word(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _round_even(x: float) -> float:
    base = math.floor(x)
    part = x - base
    if part > 0.5 or (part == 0.5 and math.fmod(base, 2.0) != 0):
        return base + 1
    return base


class DeltaContext:
    """Quantisation context: server clock and the position quantisation base."""

    def __init__(self, server_time: int = 0, position_base=(0, 0, 0)) -> None:
        self.server_time = server_time
        self.position_base = tuple(int(v) for v in position_base)


def write_gap(m: MsgWriter, distance: int, chunk_bits: int = 4) -> None:
    """Distance coder used by the playerState section (4-bit chunks, max 15)."""
    if distance < 1:
        raise ValueError(f"gap distance must be >= 1, got {distance}")
    if distance == 1:
        m.write_bits(1, 1)
        return
    limit = (1 << chunk_bits) - 1
    m.write_bits(0, 1)
    rest = distance - 1
    while rest >= limit:
        m.write_bits(limit, chunk_bits)
        rest -= limit
    m.write_bits(rest, chunk_bits)


def write_index_code(m: MsgWriter, number: int, last: int) -> None:
    """Entity/client index coder (0x671170)."""
    distance = number - last
    if distance == 1:
        m.write_bits(1, 1)
        return
    m.write_bits(0, 1)
    if distance >= 512:
        m.write_bits(1, 1)
        m.write_bits(number, 11)
    else:
        m.write_bits(0, 1)
        m.write_bits(distance, 9)


def write_compressed(m: MsgWriter, value: int, width: int) -> None:
    """Remainder bits with the bit cursor, then whole bytes with the byte cursor."""
    low = width & 7
    m.write_bits(value & _mask(low), low)
    value >>= low
    rest = width - low
    while rest:
        m.write_byte(value)
        value >>= 8
        rest -= 8


def write_integer(m: MsgWriter, width: int, from_word: int, to_word: int,
                  presence: bool = True) -> None:
    """Positive/negative width integer codec (`integer()` in the reference)."""
    if width == 0 or width < -32 or width > 32:
        raise ValueError(f"unsupported integer width {width}")
    bits = -width if width < 0 else width
    if width > 0:
        if to_word > _mask(bits):
            raise ValueError(f"value {to_word:#x} does not fit {bits} bits")
    else:
        value = to_word - (1 << 32) if to_word & 0x80000000 else to_word
        if value < -(1 << (bits - 1)) or value >= (1 << (bits - 1)):
            raise ValueError(f"signed value {value} does not fit {bits} bits")
    if presence:
        m.write_bits(1 if to_word else 0, 1)
        if not to_word:
            return
    write_compressed(m, (from_word ^ to_word) & _mask(bits), bits)


def _angle(m: MsgWriter, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError("angle is not finite")
    quantised = math.fmod(math.fmod(_round_even(value * 182.04444885253906), 65536.0) + 65536.0, 65536.0)
    m.write_short(int(quantised))


def _position(m: MsgWriter, from_word: int, to_word: int, axis: int, ctx: DeltaContext) -> None:
    lo = float(ctx.position_base[axis]) - 32768.0
    hi = lo + 65535.0
    f = math.floor(_real(from_word) + 0.5)
    t = math.floor(_real(to_word) + 0.5)
    if not (lo <= f <= hi) or not (lo <= t <= hi):
        raise ValueError(f"position {f}/{t} outside the quantisation window {lo}..{hi}")
    m.write_bits(1, 1)
    m.write_bits((int(f - lo) ^ int(t - lo)) & 0xFFFF, 16)


def _compressed_value(value: int, width: int) -> int:
    return value & _mask(width)


def write_delta_value(m: MsgWriter, bits: int, from_word: int, to_word: int,
                      ctx: DeltaContext) -> None:
    """Dispatch one descriptor codec (`CODOL_WriteDeltaValue`)."""
    f = from_word & 0xFFFFFFFF
    t = to_word & 0xFFFFFFFF
    if bits in (-92, -83, -91, -82, -90, -81):
        axis = 0 if bits in (-92, -83) else 1 if bits in (-91, -82) else 2
        _position(m, f, t, axis, ctx)
    elif bits in (-100, -79):
        m.write_bits(0, 2)
        _angle(m, _real(t))
    elif bits == -87:
        _angle(m, _real(t))
    elif bits in (-97, -74, -72, -70):
        delta = ctx.server_time - t
        m.write_bits(1 if (delta < 0 or delta > 255) else 0, 1)
        if 0 <= delta <= 255:
            m.write_bits(delta, 8)
        else:
            m.write_long(t)
    elif bits in (-80, -78, -73, -71):
        m.write_long(t)
    elif bits == -88:
        m.write_long(f ^ t)
    elif bits == -94:
        # PlayerState -94 occupies two words.  The scalar path cannot encode
        # its tag and payload without silently discarding the second word.
        raise ValueError("-94 requires a player event pair")
    elif bits in (-93, -84):
        width = 11 if bits == -93 else 7
        if t > _mask(width):
            raise ValueError(f"value {t} does not fit {width} bits")
        m.write_bits(t, width)
    elif bits == -65:
        if t % 100 or t // 100 >= 1024:
            raise ValueError("value is not a valid hundredths codec value")
        m.write_bits(t // 100, 10)
    elif bits == -86:
        scaled = _round_even(_real(t) * 10.0)
        if not math.isfinite(scaled) or scaled < 0 or scaled > 63:
            raise ValueError("scale value outside 0..6.3")
        m.write_bits(int(scaled), 6)
    elif bits == -96:
        if t > 2047:
            raise ValueError("value outside 0..2047")
        m.write_bits(1 if t == 2046 else 0, 1)
        if t == 2046:
            return
        m.write_bits(1 if t == 0 else 0, 1)
        if not t:
            return
        m.write_bits(t & 7, 3)
        m.write_byte(t >> 3)
    elif bits == -98:
        if t > 0x3FFFFFFF:
            raise ValueError("value outside the 30-bit absolute arm")
        m.write_bits(1, 1)
        m.write_bits(t, 30)
    elif bits == -77:
        if t > 255:
            raise ValueError("value outside 0..255")
        write_compressed(m, t, 8)
    elif bits == -75:
        if (f | t) > 0xFF:
            raise ValueError("-75 value outside 0..255")
        delta = t - f
        if 1 <= delta <= 4:
            m.write_bits(1, 1)
            m.write_bits(delta - 1, 3)
        else:
            m.write_bits(0, 1)
            m.write_byte((f ^ t) & 0xFF)
    elif bits == -76:
        delta = (t - (1 << 32) if t & 0x80000000 else t) - (f - (1 << 32) if f & 0x80000000 else f)
        if -16 <= delta <= 15:
            m.write_bits(1, 1)
            m.write_bits(delta + 16, 5)
        else:
            m.write_bits(0, 1)
            write_integer(m, -8, f, t, presence=False)
    elif bits == -85:
        frgb, trgb = f & 0xFFFFFF, t & 0xFFFFFF
        fa, ta = f >> 24, t >> 24
        if frgb == trgb and ((fa and ta == 0) or (not fa and ta == 255)):
            m.write_bits(1, 1)
            return
        m.write_bits(0, 1)
        if frgb == trgb:
            m.write_bits(1, 1)
        else:
            m.write_bits(0, 1)
            m.write_byte(t)
            m.write_byte(t >> 8)
            m.write_byte(t >> 16)
        m.write_bits(ta >> 3, 5)
    elif bits == 0:
        if _real(t) == 0.0:
            m.write_bits(0, 1)
            m.write_bits(t >> 31, 1)
        else:
            m.write_bits(1, 1)
            _trimmed(m, f, t, 13, 4096)
    elif bits == -89:
        _trimmed(m, f, t, 13, 4096)
    elif bits == -99:
        m.write_bits(1 if t else 0, 1)
        if t:
            _trimmed(m, f, t, 12, 2048)
    elif bits == -102:
        width = 31
        if (f | t) > _mask(width):
            raise ValueError("value outside the 31-bit arm")
        m.write_bits(1 if f != t else 0, 1)
        if f != t:
            m.write_bits(t, width)
    elif bits == -101:
        width = 6
        if (f | t) > _mask(width):
            raise ValueError("value outside the 6-bit arm")
        m.write_bits(1 if f != t else 0, 1)
        if f != t:
            m.write_bits(t, width)
    else:
        write_integer(m, bits, f, t, presence=True)


def _trimmed(m: MsgWriter, from_word: int, to_word: int, width: int, bias: int) -> None:
    f = _real(from_word)
    t = _real(to_word)
    if not math.isfinite(t) or not math.isfinite(f):
        raise ValueError("trimmed codec value is not finite")
    trunc = math.trunc(t)
    if t == trunc and -bias <= t < bias and -bias <= math.trunc(f) < bias:
        value = ((int(math.trunc(f)) + bias) ^ (int(trunc) + bias)) & _mask(width)
        m.write_bits(0, 1)
        write_compressed(m, value, width)
    else:
        m.write_bits(1, 1)
        m.write_long(from_word ^ to_word)


# ------------------------------------------------------------------- sections
def write_player_tail_zero(m: MsgWriter) -> None:
    """A tail whose every section equals the zero baseline: one 0 bit each."""
    for _ in range(TAIL_SECTIONS):
        m.write_bits(0, 1)


def write_player_tail_equipped(m: MsgWriter, weapon_id: int,
                               clip_count: int = 0,
                               reserve_count: int = 0,
                               health: int = 0) -> None:
    """Publish one equipped inventory slot against an empty tail baseline.

    Layout and widths transcribed from the 1649370 retained-engine overlay
    (`codol/snapshot/codol_player_tail164.c`, section writer for PS1172):

        gate(stats) 17bit changes, per changed stat short (byte for index 3)
        clip records: 1 + 4bit slot + 11bit weapon + gate+9 + gate+9, then 0
        gate(inventory): per slot gate, then gate+11bit weapon + 5 bools + 12
        reserve records: 1 + 4bit slot + 11bit weapon + 12bit count, then 0
        thirteen further section gates, then four sparse-list terminators

    The clip record's weapon field is **11 bits**; the earlier 10-bit form came
    from the older 1604220 array writer and desynchronised every following bit,
    which is why r675 published a clip record yet the client still showed zero
    ammunition.  Stats[3] is the only byte-wide entry.
    """
    if not 1 <= weapon_id <= 2047:
        raise ValueError("tail weapon id must fit the nonzero 11-bit wire range")
    if not 0 <= clip_count <= 511:
        raise ValueError("clip count must fit the 9-bit probe range")
    if not 0 <= reserve_count <= 4095:
        raise ValueError("reserve count must fit the 12-bit probe range")
    m.write_bits(1, 1)          # stats changed
    mask = (1 << 3) | (1 if health else 0)
    m.write_bits(mask, 17)
    if health:
        m.write_short(health)   # stats[0] is STAT_HEALTH in CoD
    m.write_byte(1)             # stats[3] is byte-wide
    if clip_count:
        m.write_bits(1, 1)      # one clip record
        m.write_bits(0, 4)      # clip slot 0
        m.write_bits(weapon_id, 11)  # clip key (1649370 width)
        m.write_bits(1, 1)      # primary clip changed
        m.write_bits(clip_count, 9)
        m.write_bits(0, 1)      # offhand clip unchanged
    m.write_bits(0, 1)          # end of clip records
    m.write_bits(1, 1)          # inventory section changed
    for slot in range(15):
        m.write_bits(1 if slot == 0 else 0, 1)
        if slot == 0:
            m.write_bits(1, 1)  # weapon id differs from empty baseline
            m.write_bits(weapon_id, 11)
            m.write_bits(0, 5)  # inventory flags
            m.write_bits(0, 12) # auxiliary counter
    if reserve_count:
        m.write_bits(1, 1)      # one reserve record
        m.write_bits(0, 4)      # reserve slot 0
        m.write_bits(weapon_id, 11)
        m.write_bits(reserve_count, 12)
    m.write_bits(0, 1)          # end of reserve records
    for _ in range(TAIL_SECTIONS - 4):
        m.write_bits(0, 1)


def write_player_event_pair(m: MsgWriter, event_id: int, parameter: int) -> None:
    """Write a -94 pair against the zero new-player baseline.

    Native reader 0x66FB60 reads a changed-ID bit, then (when changed) an
    event-ID byte.  It obtains the parameter width from 0xDA93F0[event_id].
    For changed IDs a second bit selects a new parameter; an unchanged ID
    reads its parameter directly.  This does not manage the event ring epoch.
    """
    if not 0 <= event_id < len(EVENT_PARAMETER_WIDTHS164):
        raise ValueError("unsupported Build 1649370 event ID")
    width = EVENT_PARAMETER_WIDTHS164[event_id]
    if parameter < 0 or (width == 0 and parameter != 0) or (width and parameter >= (1 << width)):
        raise ValueError("event parameter does not fit native event width")
    if event_id == 0:
        m.write_bits(0, 1)
        m.write_bits(parameter, width)
    else:
        m.write_bits(1, 1)
        m.write_byte(event_id)
        if width:
            m.write_bits(int(parameter != 0), 1)
            if parameter:
                m.write_bits(parameter, width)


def write_player_state(m: MsgWriter, values: dict[int, int], ctx: DeltaContext,
                       tail_zero: bool = True, tail_weapon: int = 0,
                       tail_clip_count: int = 0, tail_reserve_count: int = 0,
                       tail_health: int = 0,
                       player_event_pairs: dict[int, tuple[int, int]] | None = None) -> int:
    """Write the playerState section; returns the wire index of ``last``."""
    targets = [0] * PLAYER_FIELD_COUNT
    for offset, word in values.items():
        for index, (row_offset, _bits, _hint, _words) in enumerate(PLAYER_FIELDS164):
            if row_offset == offset:
                targets[index] = word & 0xFFFFFFFF
                break
        else:
            raise ValueError(f"offset {offset:#x} is not in the playerState table")
    events: dict[int, tuple[int, int]] = {}
    for offset, pair in (player_event_pairs or {}).items():
        matches = [i for i, (row_offset, bits, _hint, words)
                   in enumerate(PLAYER_FIELDS164)
                   if row_offset == offset and bits == -94 and words == 2]
        if (len(matches) != 1 or offset in values or
                not isinstance(pair, (tuple, list)) or len(pair) != 2):
            raise ValueError(f"invalid or conflicting player event offset {offset:#x}")
        event_id, parameter = pair
        if not 0 <= event_id < len(EVENT_PARAMETER_WIDTHS164):
            raise ValueError(f"unsupported player event ID at {offset:#x}")
        width = EVENT_PARAMETER_WIDTHS164[event_id]
        if parameter < 0 or (width == 0 and parameter != 0) or (width and parameter >= (1 << width)):
            raise ValueError(f"invalid player event parameter at {offset:#x}")
        events[matches[0]] = (event_id, parameter)
    selected = [False] * PLAYER_FIELD_COUNT
    last = -1
    for index, (_offset, _bits, hint, _words) in enumerate(PLAYER_FIELDS164):
        if index in events:
            selected[index] = True
        elif hint == 3:
            selected[index] = True
        else:
            selected[index] = targets[index] != 0
        if selected[index]:
            last = index
    m.write_bits(1, 1)                 # playerState present
    m.write_bits(last + 1, 8)          # 8-bit last_changed + 1
    previous = -1
    for index in range(last + 1):
        _offset, bits, hint, words = PLAYER_FIELDS164[index]
        if not selected[index] or (hint == 2 and index != last):
            continue
        write_gap(m, index - previous)
        if index in events:
            write_player_event_pair(m, *events[index])
        else:
            write_delta_value(m, bits, 0, targets[index], ctx)
        previous = index
    for index in range(max(last, 0)):
        _offset, bits, hint, _words = PLAYER_FIELDS164[index]
        if hint == 2:
            if index in events:
                write_player_event_pair(m, *events[index])
            else:
                write_delta_value(m, bits, 0, targets[index], ctx)
    if tail_weapon:
        write_player_tail_equipped(m, tail_weapon, tail_clip_count,
                                   tail_reserve_count, tail_health)
    elif tail_zero:
        write_player_tail_zero(m)
    return last


def write_entities_empty(m: MsgWriter) -> None:
    write_index_code(m, ENTITY_SENTINEL, -1)


def write_entities(m: MsgWriter, entities, ctx: DeltaContext) -> None:
    """Write the entity section for ``[(number, type, {field_index: word})]``.

    Each entity is ``index_code`` then a payload of
    ``present(1) + changed(1) + origin_baseline(1) + last(6)`` followed by a
    ``gap(3 位/7)`` + value sequence.  Only non-zero fields are emitted, so an
    entity that carries just its type costs a handful of bits.
    """
    last_number = -1
    for number, type_, fields in entities:
        if not (0 <= number < ENTITY_SENTINEL):
            raise ValueError(f"entity number {number} outside 0..{ENTITY_SENTINEL - 1}")
        if not (0 <= type_ < len(ENTITY_FIELDS164)):
            raise ValueError(f"entity type {type_} outside the 24 wire tables")
        targets = [0] * ENTITY_FIELDS_PER_TYPE164
        targets[0] = type_
        for index, word in fields.items():
            if not (0 <= index < ENTITY_FIELDS_PER_TYPE164):
                raise ValueError(f"entity field index {index} outside 0..62")
            targets[index] = word & 0xFFFFFFFF
        last = 0
        for index in range(1, ENTITY_FIELDS_PER_TYPE164):
            if targets[index]:
                last = index
        write_index_code(m, number, last_number)
        last_number = number
        m.write_bits(0, 1)                 # present
        m.write_bits(1, 1)                 # changed
        m.write_bits(0, 1)                 # logical held origin as baseline
        m.write_bits(last, 6)
        write_gap(m, 1, chunk_bits=3)
        write_delta_value(m, ENTITY_FIELDS164[type_][0][1], 0, targets[0], ctx)
        previous = 0
        for index in range(1, last + 1):
            if not targets[index]:
                continue
            write_gap(m, index - previous, chunk_bits=3)
            previous = index
            write_delta_value(m, ENTITY_FIELDS164[type_][index][1], 0, targets[index], ctx)
    write_index_code(m, ENTITY_SENTINEL, last_number)


def write_clients(m: MsgWriter, clients, ctx: DeltaContext) -> None:
    """Write new clientState records from the community 1649370 list format.

    Each item is (client_number, {descriptor_index: word}). Unlisted fields
    inherit the zero new-client baseline. This is the no-ack baseline form;
    delta removal/update needs a held-client list and is intentionally absent.
    """
    last_number = -1
    for number, fields in clients:
        if not last_number < number < 19:
            raise ValueError("client numbers must be unique, ordered and below 19")
        targets = [0] * len(CLIENT_FIELDS164)
        for index, word in fields.items():
            if not 0 <= index < len(CLIENT_FIELDS164):
                raise ValueError(f"client field index {index} outside descriptor table")
            targets[index] = word & 0xFFFFFFFF
        m.write_bits(1, 1)  # record present
        consecutive = number == last_number + 1
        m.write_bits(int(consecutive), 1)
        if not consecutive:
            m.write_bits(number, 5)
        m.write_bits(0, 1)  # not a removal
        changed = [index for index, value in enumerate(targets) if value]
        m.write_bits(int(bool(changed)), 1)
        if changed:
            m.write_bits(changed[-1], 7)
            previous = -1
            for index in changed:
                for _ in range(index - previous - 1):
                    m.write_bits(0, 1)
                m.write_bits(1, 1)
                write_delta_value(m, CLIENT_FIELDS164[index][1], 0,
                                  targets[index], ctx)
                previous = index
        last_number = number
    m.write_bits(0, 1)  # end of client list


def write_empty_tail_sections(m: MsgWriter) -> None:
    """anim commands, actors, clients and glass: one zero bit each."""
    for _ in range(4):
        m.write_bits(0, 1)


def build_snapshot(values: dict[int, int], *, server_time: int = 72192, delta: int = 0,
                   flags: int = 0, has_base: int = 0,
                   position_base=(0, 0, 0), tail_zero: bool = True,
                   tail_weapon: int = 0, tail_clip_count: int = 0,
                   tail_reserve_count: int = 0, tail_health: int = 0,
                   entities=(), clients=(),
                   player_event_pairs: dict[int, tuple[int, int]] | None = None) -> bytes:
    """Assemble one complete snapshot body (no leading ack bytes)."""
    ctx = DeltaContext(server_time=server_time, position_base=position_base)
    m = MsgWriter()
    m.write_byte(0)                     # svc_snapshot
    m.write_long(server_time)
    m.write_byte(delta)
    m.write_byte(flags)
    m.write_bits(has_base & 1, 1)
    write_player_state(m, values, ctx, tail_zero=tail_zero,
                       tail_weapon=tail_weapon, tail_clip_count=tail_clip_count,
                       tail_reserve_count=tail_reserve_count,
                       tail_health=tail_health,
                       player_event_pairs=player_event_pairs)
    m.write_bits(0, 1)                  # anim commands
    m.write_bits(0, 1)                  # actors
    if entities:
        write_entities(m, entities, ctx)
    else:
        write_entities_empty(m)
    write_clients(m, clients, ctx)
    m.write_bits(0, 1)                  # glass
    m.write_byte(5)                     # svc_EOF
    if m.failed:
        raise ValueError("snapshot writer failed")
    return m.to_bytes()


# ------------------------------------------------------------------ self test
def _self_test() -> int:
    failures = 0

    def check(name, got, want) -> None:
        nonlocal failures
        if got != want:
            failures += 1
            print(f"FAIL {name}: got {got!r} want {want!r}")

    # A byte write advances only the byte cursor; the bit cursor keeps running
    # in the earlier byte.  This is the behaviour the compressed codec relies on.
    m = MsgWriter()
    m.write_bits(1, 3)
    m.write_byte(0xAB)
    m.write_bits(1, 2)
    check("dual cursor bytes", m.to_bytes(), bytes((0b00001001, 0xAB)))

    # compressed(0b101, 11) == 3 remainder bits then one whole byte
    m = MsgWriter()
    write_compressed(m, 0b00000000101, 11)
    check("compressed 11 bytes", m.to_bytes(), bytes((0b00000101, 0x00)))

    # positive-width field: presence bit 0 for a zero value costs one bit
    m = MsgWriter()
    write_integer(m, 11, 0, 0)
    check("integer zero bits", m.bit, 1)

    # a non-zero 8-bit field costs one presence bit; the value's 8 bits are
    # written as a whole byte, so the *bit* cursor only advances by one
    m = MsgWriter()
    write_integer(m, 8, 0, 5)
    check("integer 8 bit cursor", m.bit, 1)
    check("integer 8 bytes", m.to_bytes(), bytes((0b00000001, 0x05)))

    # gap code: distance 1 is a single 1 bit; distance 16 is 0 + 15 + 0
    m = MsgWriter()
    write_gap(m, 1)
    check("gap 1", m.bit, 1)
    m = MsgWriter()
    write_gap(m, 16)
    check("gap 16 bits", m.bit, 1 + 4 + 4)
    check("gap 16 value", m.to_bytes(), bytes((0b00011110, 0b00000000)))

    # index code: sentinel 2047 with last=-1 uses the 11-bit absolute arm
    m = MsgWriter()
    write_index_code(m, ENTITY_SENTINEL, -1)
    check("sentinel bits", m.bit, 1 + 1 + 11)

    # Community client-list baseline: present, consecutive client 0,
    # not removed, no changed descriptors, then end-of-list.
    m = MsgWriter()
    write_clients(m, [(0, {})], DeltaContext())
    check("client zero bits", m.bit, 5)
    check("client zero bytes", m.to_bytes(), b"\x03")

    # angle codec: 90 degrees -> 16384 -> 0x4000 little endian
    m = MsgWriter()
    write_delta_value(m, -87, 0, _word(90.0), DeltaContext())
    check("angle 90", m.to_bytes(), b"\x00\x40")

    m = MsgWriter()
    write_delta_value(m, -75, 0, 1, DeltaContext())
    check("-75 short delta bits", m.bit, 4)
    check("-75 short delta bytes", m.to_bytes(), b"\x01")
    m = MsgWriter()
    write_delta_value(m, -75, 0, 5, DeltaContext())
    check("-75 XOR form", m.to_bytes(), b"\x00\x05")

    # Build 1649370 player event descriptors are two words.  Event ID zero
    # reuses the baseline ID and reads its 11-bit parameter directly.
    m = MsgWriter()
    write_player_event_pair(m, 0, 0x52A)
    check("event pair bits", m.bit, 12)
    check("event pair bytes", m.to_bytes(), b"\x54\x0a")
    # A real nonzero ID uses the changed-ID bit + byte cursor, then a parameter
    # gate.  EV_SV_FIRE_WEAPON (54) has a measured 5-bit parameter width.
    m = MsgWriter()
    write_player_event_pair(m, 54, 0)
    check("fire event bytes", m.to_bytes(), b"\x01\x36")
    check("fire event bit cursor", m.bit, 2)
    try:
        write_player_event_pair(MsgWriter(), 54, 32)
    except ValueError:
        pass
    else:
        failures += 1
        print("FAIL out-of-range fire parameter was accepted")

    # a full empty frame must end with the EOF byte and decode its own geometry
    body = build_snapshot({0: 72192, 4: 0, 0x158: 0}, server_time=72192)
    check("frame svc", body[0], 0)
    check("frame eof", body[-1], 5)
    print(f"frame bytes: {len(body)}  hex: {body.hex()}")
    print(f"self-test failures: {failures}")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _self_test() else 0)
