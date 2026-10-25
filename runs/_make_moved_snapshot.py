"""Move the spawn point in the real baseline snapshot and see if cl follows.

Layout found in baseline-outer17-245.bin (little-endian floats):

    0x0F..0x12  00 00 a8 43  -> 336.0
    0x14..0x17  00 80 82 43  -> 261.0
    0x18..0x1B  00 00 70 42  ->  60.0

while the client keeps them at cl+0x3C80/84/88 = (336.0, 60.0, 261.0).

So the snapshot order is (x, z, y) or the client reorders.  This script writes a
clearly distinct triple (500, 120, 300) into the snapshot and lets us check
whether cl+0x3C80/84/88 follows -- which would prove the snapshot -> cl->playerState
chain and give us a way to move the player from the server side.
"""
import pathlib
import struct

SRC = pathlib.Path("runs/demo-outer-exact/baseline-outer17-245.bin")
OUT = pathlib.Path("runs/snap-moved.bin")

src = bytearray(SRC.read_bytes())
print("  src %d bytes, head=%s" % (len(src), src[:12].hex(" ")))

# verify the three floats first
for off, want in ((0x0F, 336.0), (0x14, 261.0), (0x18, 60.0)):
    got = struct.unpack_from("<f", src, off)[0]
    print("  offset %#04x: %.3f  (expected %.3f)  %s"
          % (off, got, want, "OK" if abs(got - want) < 0.01 else "MISMATCH"))

# write a distinctive triple
NEW = {0x0F: 500.0, 0x14: 120.0, 0x18: 300.0}
for off, val in NEW.items():
    struct.pack_into("<f", src, off, val)
    print("  wrote offset %#04x = %.1f" % (off, val))

OUT.write_bytes(bytes(src))
assert len(src) == 245, len(src)
print("  wrote %s (%d bytes, length unchanged)" % (OUT, len(src)))
print()
print("  new bytes 0x08..0x20:", bytes(src[0x08:0x20]).hex(" "))
for off, want in ((0x0F, 500.0), (0x14, 120.0), (0x18, 300.0)):
    print("  verify %#04x = %.1f" % (off, struct.unpack_from("<f", src, off)[0]))
