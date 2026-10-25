"""Analyse the configstring layout inside the captured gamestate file."""
import pathlib

PATH = pathlib.Path("runs/demo-outer-exact/gamestate-network-ffb56d7e-6411.bin")
b = PATH.read_bytes()

print("  file size:", len(b))
print("  first 48 bytes:", b[:48].hex(" "))
print()

for needle in (b"g_gametype", b"mp_crash_tropical", b"war", b"cod"):
    idx = b.find(needle)
    print("  needle %-20r first offset: %s" % (needle, idx))
    if idx >= 0:
        lo = max(0, idx - 24)
        print("    bytes before :", b[lo:idx].hex(" "))
        print("    bytes at     :", b[idx:idx + 64])
    print()

print("  NUL-separated view of the first 200 bytes after offset 4:")
seg = b[4:200]
for i, part in enumerate(seg.split(b"\x00")[:14]):
    try:
        s = part.decode("latin-1")
    except Exception:
        s = repr(part)
    printable = all(32 <= ord(c) < 127 for c in s) if s else True
    print("    [%2d] len=%3d printable=%s  %r" % (i, len(part), printable, s[:70]))
