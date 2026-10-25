"""Build 1649370 gamestate codec -- parse AND re-encode, verified by round-trip.

The reference server (protocol-1604220) shows the mechanism:
    tag3 | server_command_sequence u32 | map string | zone string | checksum u32
    | tag4 | configstrings | tag5 | client_number u32 | checksum_feed u32 | tag5

ConfigStrings:
    count u16
    text[]:  index = 1 bit ("== prev+1") else 14 bits absolute ; then NUL string
    simple:  count 10 bits ; per entry index + 11 bits model
    complex: count 11 bits ; per entry index + 11 + 8 + 1(+9) + 4(+14*n)

A byte-exact round-trip proves our field widths match the real file, which is
what lets us change content (client_number, adding player entries) safely
instead of poking fixed offsets.

Usage:
    python tools/build_gamestate_1649370.py --check  <file.bin>
    python tools/build_gamestate_1649370.py --set-client <n> --in <f> --out <f>
"""
import argparse
import pathlib
import sys

MAX_TEXT_BYTES = 8191
SLOT_COUNT = 12761
PREVIEW = "runs"  # only used for diagnostics


class CodecError(Exception):
    pass


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.bit = 0

    def raw(self, n):
        end = self.pos + n
        if end > len(self.data):
            raise CodecError("truncated: need %d at byte %d" % (n, self.pos))
        v = self.data[self.pos:end]
        self.pos = end
        return v

    def byte(self):
        return self.raw(1)[0]

    def u16(self):
        return int.from_bytes(self.raw(2), "little")

    def u32(self):
        return int.from_bytes(self.raw(4), "little")

    def bits(self, width):
        v = 0
        for shift in range(width):
            if self.bit & 7 == 0:
                self.bit = self.pos * 8
                self.raw(1)
            idx = self.bit >> 3
            if idx >= len(self.data):
                raise CodecError("bitstream past end at bit %d" % self.bit)
            v |= ((self.data[idx] >> (self.bit & 7)) & 1) << shift
            self.bit += 1
        return v

    def string(self, maxlen=MAX_TEXT_BYTES):
        out = bytearray()
        while True:
            c = self.byte()
            if c == 0:
                return bytes(out)
            if len(out) >= maxlen:
                raise CodecError("string too long")
            out.append(c)


class Writer:
    def __init__(self):
        self.buf = bytearray()
        self.bit = 0

    def raw(self, b):
        self.buf.extend(b)

    def byte(self, v):
        self.raw(bytes([v & 0xFF]))

    def u16(self, v):
        self.raw(int(v).to_bytes(2, "little"))

    def u32(self, v):
        self.raw((int(v) & 0xFFFFFFFF).to_bytes(4, "little"))

    def bits(self, value, width):
        for shift in range(width):
            if self.bit & 7 == 0:
                self.bit = len(self.buf) * 8
                self.raw(b"\x00")
            if (value >> shift) & 1:
                self.buf[self.bit >> 3] |= 1 << (self.bit & 7)
            self.bit += 1

    def string(self, b):
        self.raw(b)
        self.raw(b"\x00")

    def finish(self):
        return bytes(self.buf)


def read_index(r, prev):
    if r.bits(1) == 1:
        return 0 if prev is None else prev + 1
    return r.bits(14)


def write_index(w, index, prev):
    nxt = 0 if prev is None else prev + 1
    w.bits(1 if index == nxt else 0, 1)
    if index != nxt:
        w.bits(index, 14)


class Gamestate:
    def __init__(self):
        self.prefix = b""          # gs 4-byte framing, preserved verbatim
        self.server_command_sequence = 0
        self.map_name = b""
        self.zone_name = b""
        self.checksum = 0
        self.texts = []            # [(index, bytes)]
        self.simple = []           # [(index, model)]
        self.complex = []          # [(index, model, f8, f9, [att])]
        self.client_number = 0
        self.checksum_feed = 0


def decode(data):
    g = Gamestate()
    # gs prefixes the body with 4 framing bytes; tag3 follows
    start = 4 if (len(data) > 4 and data[:1] != b"\x03" and data[4:5] == b"\x03") else 0
    g.prefix = data[:start]
    r = Reader(data[start:])
    tag = r.byte()
    if tag != 3:
        raise CodecError("expected tag3, got %d" % tag)
    g.server_command_sequence = r.u32()
    g.map_name = r.string(31)
    g.zone_name = r.string(31)
    g.checksum = r.u32()
    if r.byte() != 4:
        raise CodecError("expected tag4")
    count = r.u16()
    if count > SLOT_COUNT:
        raise CodecError("configstring count %d > %d" % (count, SLOT_COUNT))
    prev = None
    for _ in range(count):
        idx = read_index(r, prev)
        g.texts.append((idx, r.string()))
        prev = idx
    prev = None
    n = r.bits(10)
    for _ in range(n):
        idx = read_index(r, prev)
        g.simple.append((idx, r.bits(11)))
        prev = idx
    prev = None
    n = r.bits(11)
    for _ in range(n):
        idx = read_index(r, prev)
        model = r.bits(11)
        f8 = r.bits(8)
        f9 = r.bits(9) if r.bits(1) == 1 else None
        na = r.bits(4)
        att = [r.bits(14) for _ in range(na)]
        g.complex.append((idx, model, f8, f9, att))
        prev = idx
    if r.byte() != 5:
        raise CodecError("expected tag5 before client_number")
    g.client_number = r.u32()
    g.checksum_feed = r.u32()
    if r.byte() != 5:
        raise CodecError("expected trailing tag5")
    consumed = start + r.pos
    if consumed != len(data):
        raise CodecError("trailing %d bytes" % (len(data) - consumed))
    return g


def encode(g):
    w = Writer()
    w.raw(g.prefix)
    w.byte(3)
    w.u32(g.server_command_sequence)
    w.string(g.map_name)
    w.string(g.zone_name)
    w.u32(g.checksum)
    w.byte(4)
    if len(g.texts) > SLOT_COUNT:
        raise CodecError("too many configstrings")
    w.u16(len(g.texts))
    prev = None
    for idx, val in g.texts:
        write_index(w, idx, prev)
        w.string(val)
        prev = idx
    w.bits(len(g.simple), 10)
    prev = None
    for idx, model in g.simple:
        write_index(w, idx, prev)
        w.bits(model, 11)
        prev = idx
    w.bits(len(g.complex), 11)
    prev = None
    for idx, model, f8, f9, att in g.complex:
        write_index(w, idx, prev)
        w.bits(model, 11)
        w.bits(f8, 8)
        w.bits(1 if f9 is not None else 0, 1)
        if f9 is not None:
            w.bits(f9, 9)
        w.bits(len(att), 4)
        for a in att:
            w.bits(a, 14)
        prev = idx
    w.byte(5)
    w.u32(g.client_number)
    w.u32(g.checksum_feed)
    w.byte(5)
    return w.finish()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="FILE", help="parse + round-trip verify")
    ap.add_argument("--in", dest="src", help="input gamestate")
    ap.add_argument("--out", dest="dst", help="output gamestate")
    ap.add_argument("--set-client", type=int, help="override client_number")
    ap.add_argument("--add-player", type=int, metavar="INDEX",
                    help="insert a text configstring at INDEX (probe)")
    ap.add_argument("--add-value", default="", help="value for --add-player")
    args = ap.parse_args()

    files = [args.check] if args.check else [args.src]
    for f in files:
        if not f:
            continue
        data = pathlib.Path(f).read_bytes()
        g = decode(data)
        again = encode(g)
        print("FILE %s (%d B)" % (f, len(data)))
        print("  prefix=%r  seq=%d  map=%r  zone=%r  checksum=%#010x"
              % (g.prefix, g.server_command_sequence, g.map_name, g.zone_name, g.checksum))
        print("  configstrings: %d text / %d simple / %d complex  (index %d..%d)"
              % (len(g.texts), len(g.simple), len(g.complex),
                 min(i for i, _ in g.texts) if g.texts else -1,
                 max(i for i, _ in g.texts) if g.texts else -1))
        print("  client_number=%d  checksum_feed=%#010x"
              % (g.client_number, g.checksum_feed))
        ok = again == data
        print("  re-encode: %d B  %s" % (len(again), "**BYTE-EXACT ROUND-TRIP**" if ok else "MISMATCH"))
        if not ok:
            for i, (a, b) in enumerate(zip(data, again)):
                if a != b:
                    print("    first diff at %#x: %02x != %02x" % (i, a, b))
                    break
            raise SystemExit(1)

    if args.src and args.dst:
        g = decode(pathlib.Path(args.src).read_bytes())
        if args.set_client is not None:
            print("  client_number: %d -> %d" % (g.client_number, args.set_client))
            g.client_number = args.set_client
        if args.add_player is not None:
            val = args.add_value.encode("latin-1")
            g.texts.append((args.add_player, val))
            g.texts.sort(key=lambda t: t[0])
            print("  added text configstring index=%d value=%r" % (args.add_player, val))
        out = encode(g)
        pathlib.Path(args.dst).write_bytes(out)
        # verify the produced file re-parses
        g2 = decode(out)
        print("  wrote %s (%d B); re-parse OK: client_number=%d, %d texts"
              % (args.dst, len(out), g2.client_number, len(g2.texts)))


if __name__ == "__main__":
    main()
