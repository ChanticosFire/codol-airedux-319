"""Replace configstring[2] ('cod') with a real CS_PLAYERS[0] InfoString.

COD4 layout:  CS_SERVERINFO=0, CS_SYSTEMINFO=1, CS_PLAYERS=2..
Our captured gamestate has configstring[2] == "cod", which makes the client
conclude there are no players and fall back to spectator mode.

IMPORTANT: each configstring is NUL-terminated with a real 0x00 byte, NOT the
two-character sequence backslash+'0'.
"""
import pathlib

SRC = pathlib.Path("runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin")
OUT = pathlib.Path("runs/gamestate-player-cs.bin")

src = SRC.read_bytes()
needle = b"cod\x00"
i = src.find(needle)
print("  needle 'cod' + NUL at offset:", i)
if i < 0:
    raise SystemExit("not found")

# InfoString body, then a REAL NUL terminator
info = (
    b"\\name\\Player\\team\\allies\\model\\mp_allies_rifleman"
    b"\\rank\\1\\score\\0\\ping\\50"
)
print("  info length:", len(info))

new = src[:i] + info + b"\x00" + src[i + len(needle):]
OUT.write_bytes(new)
print("  wrote %s  (%d -> %d bytes)" % (OUT, len(src), len(new)))
print()

seg = new[77:360]
print("  new configstring region from offset 77:")
for k, part in enumerate(seg.split(b"\x00")[:8]):
    try:
        s = part.decode("latin-1")
        safe = "".join(c if 32 <= ord(c) < 127 else "?" for c in s)
    except Exception:
        safe = "<binary>"
    print("    [%d] len=%3d %s" % (k, len(part), safe[:80]))
