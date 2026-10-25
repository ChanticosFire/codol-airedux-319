"""Parse a gamestate body using the reference server's InitialState layout.

Layout (protocol-1604220/src/game_initial_state.rs):
    tag3 | server_command_sequence u32 | map_name string | zone_name string
    | checksum u32 | tag4 | ConfigStrings | tag5 | client_number u32
    | checksum_feed u32 | tag5

ConfigStrings (game_configstrings.rs):
    count u16
    per text entry: index(1 bit "==prev+1" else 14 bits absolute) + NUL string
    simple_models: count 10 bits, per entry index + 11 bits model
    complex_models: count 11 bits, per entry index + 11 + 8 + 1(+9) + 4(+14*n)
"""
import pathlib
import sys

MAX_TEXT_BYTES = 8191
SLOT_COUNT = 12761


class Err(Exception):
    pass


class R:
    def __init__(self, b):
        self.b = b
        self.pos = 0
        self.bit = 0

    def raw(self, n):
        v = self.b[self.pos:self.pos + n]
        if len(v) < n:
            raise Err("truncated at byte %d (need %d)" % (self.pos, n))
        self.pos += n
        return v

    def byte(self):
        return self.raw(1)[0]

    def u16(self):
        return int.from_bytes(self.raw(2), "little")

    def u32(self):
        return int.from_bytes(self.raw(4), "little")

    def bits(self, w):
        v = 0
        for shift in range(w):
            if self.bit & 7 == 0:
                self.bit = self.pos * 8
                self.raw(1)
            idx = self.bit >> 3
            if idx >= len(self.b):
                raise Err("bitstream past end at bit %d" % self.bit)
            v |= ((self.b[idx] >> (self.bit & 7)) & 1) << shift
            self.bit += 1
        return v

    def string(self, maxlen):
        out = bytearray()
        while True:
            c = self.byte()
            if c == 0:
                return bytes(out)
            if len(out) >= maxlen:
                raise Err("string too long")
            out.append(c)


def read_index(r, prev):
    if r.bits(1) == 1:
        return 0 if prev is None else prev + 1
    return r.bits(14)


def read_configstrings(r):
    count = r.u16()
    texts = []
    prev = None
    for _ in range(count):
        idx = read_index(r, prev)
        s = r.string(MAX_TEXT_BYTES)
        texts.append((idx, s))
        prev = idx
    simple = []
    n = r.bits(10)
    prev = None
    for _ in range(n):
        idx = read_index(r, prev)
        simple.append((idx, r.bits(11)))
        prev = idx
    complex_ = []
    n = r.bits(11)
    prev = None
    for _ in range(n):
        idx = read_index(r, prev)
        model = r.bits(11)
        f8 = r.bits(8)
        f9 = r.bits(9) if r.bits(1) == 1 else None
        na = r.bits(4)
        att = [r.bits(14) for _ in range(na)]
        complex_.append((idx, model, f8, f9, att))
        prev = idx
    return texts, simple, complex_


def parse(path):
    data = pathlib.Path(path).read_bytes()
    print("=" * 78)
    print("FILE: %s  (%d bytes)" % (path, len(data)))
    print("  first 8 bytes: %s" % data[:8].hex(" "))
    print("  last  8 bytes: %s" % data[-8:].hex(" "))
    # gs prefixes the body with 4 framing bytes; locate the tag3 start
    start = 0
    if data[:1] != b'\x03' and len(data) > 4 and data[4:5] == b'\x03':
        start = 4
        print('  (skipping 4-byte gs framing prefix)')
    r = R(data[start:])
    tag = r.byte()
    print("  tag (expect 3) = %d   %s" % (tag, "OK" if tag == 3 else "MISMATCH"))
    seq = r.u32()
    print("  server_command_sequence = %d" % seq)
    map_name = r.string(31)
    print("  map_name  = %r" % map_name)
    zone_name = r.string(31)
    print("  zone_name = %r" % zone_name)
    checksum = r.u32()
    print("  checksum  = %#010x" % checksum)
    tag2 = r.byte()
    print("  tag (expect 4) = %d   %s" % (tag2, "OK" if tag2 == 4 else "MISMATCH"))
    texts, simple, complex_ = read_configstrings(r)
    print("  configstrings: %d text, %d simple, %d complex" % (len(texts), len(simple), len(complex_)))
    for idx, s in texts:
        safe = s.decode("gbk", "replace")
        print("    index %-6d (0x%04x)  %r" % (idx, idx, safe[:80]))
    if simple:
        print("    simple_models: %s" % simple[:8])
    if complex_:
        print("    complex_models: %s" % complex_[:4])
    tag3 = r.byte()
    print("  tag (expect 5) = %d   %s" % (tag3, "OK" if tag3 == 5 else "MISMATCH"))
    client_number = r.u32()
    print("  **client_number = %d**" % client_number)
    checksum_feed = r.u32()
    print("  checksum_feed = %#010x" % checksum_feed)
    tag4 = r.byte()
    print("  tag (expect 5) = %d   %s" % (tag4, "OK" if tag4 == 5 else "MISMATCH"))
    print("  consumed %d / %d bytes  %s" % (r.pos + start, len(data),
                                            "PERFECT" if r.pos == len(data) else "TRAILING %d" % (len(data) - r.pos)))


for p in sys.argv[1:]:
    try:
        parse(p)
    except Err as e:
        print("  !! parse error: %s" % e)
    print()
