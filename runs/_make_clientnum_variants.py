"""Flip the presumed clientNum byte in the gamestate header.

Layout (confirmed by analysis in §470-§475):

    offset 0..3 : 00 00 00 00      ack added by gs
    offset 4    : 03               svc_gamestate
    offset 5    : **01**           presumed clientNum
    offset 6..8 : 00 00 00
    offset 9    : "mp_crash_tropical\0"

Hypothesis: the client reads offset 5 as clientNum and therefore believes it is
player #1.  Our --connect-extra \\clientNum\\0 then conflicts, so no matching
playerstate exists and the client falls back to spectator mode.

This script writes variants with that byte set to 0 / 1 / 2, keeping the file
length identical so we do not disturb the offset-sensitive binary tail.
"""
import pathlib
import sys

SRC = pathlib.Path("runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin")
src = SRC.read_bytes()

print("  src %s (%d bytes)" % (SRC.name, len(src)))
print("  header:", src[:12].hex(" "))
assert src[4] == 0x03, "expected svc_gamestate at offset 4"
print("  offset 4 = %#04x (svc_gamestate)" % src[4])
print("  offset 5 = %#04x  <- presumed clientNum" % src[5])

for value in (0, 1, 2):
    out = pathlib.Path("runs/gamestate-clientnum-%d.bin" % value)
    new = bytearray(src)
    new[5] = value
    out.write_bytes(bytes(new))
    assert len(new) == len(src)
    print("  wrote %-36s offset5=%#04x  (%d bytes)" % (out.name, new[5], len(new)))
