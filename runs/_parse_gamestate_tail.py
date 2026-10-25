"""Parse the binary tail of the gamestate after configstring[3] ("155").

The region looks like:
    "155" 00  01 00  745 0.000106654 124 123 106 0.375 0 0 1 70 75 00
    01 b8  433.250000 98.500000 137.000000  00 00 f4 \w...

Hypothesis: it encodes entity/player records (count + fields + position),
i.e. the gamestate already carries player data -- the client just doesn't treat
it as the local player.
"""
import pathlib
import struct

PATH = pathlib.Path("runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin")
b = PATH.read_bytes()

# locate "155\0"
i = b.find(b"155\x00")
print("  '155\\0' at offset:", i)
seg = b[i:i + 0x120]
print("  raw hex of the next 0x120 bytes:")
for off in range(0, len(seg), 16):
    row = seg[off:off + 16]
    print("   %#06x  %-47s  %r" % (off, row.hex(" "),
                                   "".join(chr(c) if 32 <= c < 127 else "." for c in row)))
print()

# Interpret: after "155\0" comes 01 00
p = i + 4
if b[p:p + 2] == b"\x01\x00":
    print("  byte 01 00 right after '155\\0' -- possible count/flags")
    p += 2
print("  ascii run at p:", b[p:p + 50])

# The numeric ascii run
j = b.find(b"745 ", p)
print("  '745 ' at offset:", j)
k = b.find(b"\x00", j)
print("  numeric ascii run:", b[j:k])
vals = b[j:k].split(b" ")
print("  split into %d tokens:" % len(vals))
for t in vals:
    try:
        print("    %-14r -> float %s" % (t, float(t)))
    except ValueError:
        print("    %-14r -> (not a float)" % t)

# Then the coordinates
m = b.find(b"433.25", k)
print()
print("  '433.25' at offset:", m)
if m > 0:
    print("  16 bytes before:", b[m - 16:m].hex(" "))
    coords = b[m:b.find(b"\x00", m)]
    print("  coord string: %r" % coords)
    parts = coords.split(b" ")
    for t in parts:
        try:
            print("    %-14r -> float %s" % (t, float(t)))
        except ValueError:
            print("    %-14r -> (not a float)" % t)
