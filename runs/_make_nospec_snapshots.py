"""Zero out the three 0x01 bytes in the real baseline snapshot.

Reasoning: `playerState_t` starts with `int pm_type` and PM_SPECTATOR == 1.
The baseline was captured from a demo whose recorder was a spectator, so one of
these 0x01 bytes is very likely pm_type.

Layout of the interesting head region:

    0x020  2b 00 00 00 00 00 00 00 00 c2 00 00 00 00 **02** **01**
    0x030  00 40 00 00 9f **01** 40 00 00 a6 b0 00 **01** c9 20 03

Candidates: 0x02F, 0x035, 0x03C (all == 0x01).

Variant A: zero all three (fastest way to see whether the direction is right).
Variants B..D: zero one at a time (for bisecting later).
"""
import pathlib

SRC = pathlib.Path("runs/demo-outer-exact/baseline-outer17-245.bin")
src = SRC.read_bytes()
assert src[0] == 0x00, "expected svc_snapshot"

cands = [0x2F, 0x35, 0x3C]
for off in cands:
    print("  offset %#04x = %#04x" % (off, src[off]))
    assert src[off] == 0x01, "unexpected byte"

# Variant A: all three
a = bytearray(src)
for off in cands:
    a[off] = 0x00
pathlib.Path("runs/snap-nospec-all.bin").write_bytes(bytes(a))
print("  wrote runs/snap-nospec-all.bin (%d bytes, zeroed %s)" % (len(a), cands))

# Variants B..D: one at a time
for i, off in enumerate(cands):
    b = bytearray(src)
    b[off] = 0x00
    p = pathlib.Path("runs/snap-nospec-%d.bin" % i)
    p.write_bytes(bytes(b))
    print("  wrote %-28s zeroed offset %#04x" % (p.name, off))

# sanity dump of modified region
print()
print("  variant A head:")
for off in range(0x20, 0x48, 16):
    row = a[off:off + 16]
    print("   %#05x  %-47s  %s" % (off, row.hex(" "),
                                   "".join(chr(c) if 32 <= c < 127 else "." for c in row)))
