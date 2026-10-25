"""Analyse the 1155-byte in-band bodies -- the ones only present while keys are held.

Round 249 established:
  - idle only produces 250..300-byte bodies
  - pressing D produces mostly 1155-byte bodies (96/205)

So the usercmd lives inside the 1155-byte body.  This script:
  1. selects body_len == 1155
  2. looks for a field that increases monotonically (serverTime / commandTime)
  3. reports offsets whose value set is small (bool/small-int candidates)
  4. prints a hex window around the monotonic field so we can read the layout
"""
import json
import pathlib
import collections

LOG = pathlib.Path("runs") / "r415-gs.jsonl"
TARGET = 1155

rows = []
for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
        continue
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("dir") == "in" and r.get("kind") == "inband" and r.get("body_len") == TARGET:
        raw = bytes.fromhex(r.get("body_head", ""))
        if raw:
            rows.append((r.get("seq"), raw))

print("  bodies with body_len == %d: %d" % (TARGET, len(rows)))
if not rows:
    raise SystemExit("none found")

n = min(len(b) for _, b in rows)
print("  usable length:", n)
print()

# 1) monotonic field search: find 4-byte little-endian ints that strictly increase
print("  === candidates that increase monotonically (4-byte LE) ===")
found = []
for off in range(0, n - 4):
    vals = []
    for _, b in rows:
        vals.append(int.from_bytes(b[off:off + 4], "little"))
    inc = sum(1 for i in range(1, len(vals)) if vals[i] >= vals[i - 1])
    if inc == len(vals) - 1 and len(set(vals)) > len(vals) * 0.7:
        found.append((off, vals[0], vals[-1], len(set(vals))))
for off, v0, v1, nd in found[:12]:
    print("    off=%-4d  first=%-12d last=%-12d distinct=%d" % (off, v0, v1, nd))
print("    (total %d)" % len(found))
print()

# 2) offsets with very few distinct values (bool / small int fields)
print("  === offsets with <= 4 distinct values ===")
few = []
for off in range(n):
    vals = set(b[off] for _, b in rows)
    if len(vals) <= 4:
        few.append((off, sorted(vals)))
print("    count: %d" % len(few))
for off, vals in few[:24]:
    print("    off=%-4d values=%s" % (off, [hex(v) for v in vals]))
print()

# 3) hex window around the first monotonic field
if found:
    off0 = found[0][0]
    lo = max(0, off0 - 32)
    hi = min(n, off0 + 64)
    print("  === hex window around monotonic field at off=%d (file offsets %#x..%#x) ===" % (off0, lo, hi))
    for i, (seq, b) in enumerate(rows[:2]):
        print("    seq=%s:" % seq)
        for p in range(lo, hi, 16):
            row = b[p:p + 16]
            print("      %#05x  %-47s  %s" % (p, row.hex(" "),
                                              "".join(chr(c) if 32 <= c < 127 else "." for c in row)))
