"""Equal-length configstring test.

Replace configstring[2] value "cod" (3 bytes) with "abc" (3 bytes) so the file
length stays exactly 6411.  If the client still reaches net=10, the failure of
the previous attempt was purely a length/offset problem; if it drops to 0, the
configstring content itself is being validated.
"""
import pathlib

SRC = pathlib.Path("runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin")
OUT = pathlib.Path("runs/gamestate-cs-abc.bin")

src = SRC.read_bytes()
needle = b"cod\x00"
i = src.find(needle)
print("  'cod'+NUL at offset:", i)
assert i > 0

new = src[:i] + b"abc\x00" + src[i + len(needle):]
assert len(new) == len(src), (len(new), len(src))
OUT.write_bytes(new)
print("  wrote %s  (%d bytes, unchanged length)" % (OUT, len(new)))

# sanity: show the configstring neighbours
seg = new[77:260]
parts = seg.split(b"\x00")
for k, part in enumerate(parts[:5]):
    s = "".join(c if 32 <= ord(c) < 127 else "?" for c in part.decode("latin-1"))
    print("    [%d] len=%3d %s" % (k, len(part), s[:70]))
