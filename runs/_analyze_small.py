"""Analyse the small (200..350 byte) in-band bodies -- the only per-frame changing ones.

Round 250 showed the 1155-byte bodies are byte-identical repeats (a static blob).
The small bodies appear in every segment (idle / W / D) and are the remaining
candidate for `usercmd`.

This script:
  1. selects 200 <= body_len <= 350
  2. groups them by body_len (each size is a distinct command shape)
  3. for each group looks for a monotonically increasing 4-byte field
  4. compares per-offset value sets between idle / W / D
"""
import json
import pathlib
import collections

LOG = pathlib.Path("runs") / "r415-gs.jsonl"
MARKS = json.loads(pathlib.Path("runs/_marks2.json").read_text(encoding="utf-8"))

rows = []
for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
        continue
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("dir") == "in" and r.get("kind") == "inband":
        raw = bytes.fromhex(r.get("body_head", ""))
        if raw:
            rows.append((raw, r.get("body_len")))

b = (MARKS[1], MARKS[3], MARKS[5], MARKS[7])
segs = {"idle": rows[b[0]:b[1]], "W": rows[b[1]:b[2]], "D": rows[b[2]:b[3]]}

small = {k: [(x[0], x[1]) for x in v if isinstance(x[1], int) and 200 <= x[1] <= 350]
         for k, v in segs.items()}
print("  small bodies per segment:", {k: len(v) for k, v in small.items()})
print()

sizes = collections.Counter(x[1] for v in small.values() for x in v)
print("  sizes present:", dict(sizes.most_common(10)))
print()

for size, _ in sizes.most_common(4):
    grp = {k: [x[0] for x in v if x[1] == size] for k, v in small.items()}
    n = {k: len(v) for k, v in grp.items()}
    if sum(n.values()) < 3:
        continue
    print("=== body_len = %d   counts=%s ===" % (size, n))
    allb = [x for v in grp.values() for x in v]
    ln = min(len(x) for x in allb)
    # monotonic search
    mono = []
    for off in range(0, ln - 4):
        vals = [int.from_bytes(x[off:off + 4], "little") for x in allb]
        if all(vals[i] >= vals[i - 1] for i in range(1, len(vals))) and len(set(vals)) > len(vals) * 0.6:
            mono.append((off, vals[0], vals[-1], len(set(vals))))
    print("  monotonic 4-byte fields: %d" % len(mono))
    for off, v0, v1, nd in mono[:8]:
        print("    off=%-4d first=%-12d last=%-12d distinct=%d" % (off, v0, v1, nd))
    # per-offset difference idle vs W vs D
    if min(n.values()) > 0:
        diff = []
        for off in range(ln):
            v1 = collections.Counter(x[off] for x in grp["idle"]).most_common(1)[0][0]
            sw = set(x[off] for x in grp["W"])
            sd = set(x[off] for x in grp["D"])
            if sw != {v1} or sd != {v1}:
                wv = collections.Counter(x[off] for x in grp["W"]).most_common(1)[0][0]
                dv = collections.Counter(x[off] for x in grp["D"]).most_common(1)[0][0]
                diff.append((off, v1, wv, dv))
        print("  offsets differing between segments: %d" % len(diff))
        for off, v1, wv, dv in diff[:14]:
            print("    off=%-4d idle=%02x W=%02x D=%02x%s"
                  % (off, v1, wv, dv, "  ** W!=D **" if wv != dv else ""))
    print()
