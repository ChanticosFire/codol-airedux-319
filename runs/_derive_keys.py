"""Derive a candidate XOR key from each in-band body and see whether they agree.

Method: if the plaintext contains a run of >=12 zero bytes, the ciphertext there
equals the repeating key.  For every body we look for a 4-byte segment repeated
three times in a row; that segment is the candidate key.

If all bodies yield the same key, the cipher is a simple 4-byte cycle and we have
a fixed offset problem.  If keys differ per packet, the key is derived from
challenge/seq and we need the formula.
"""
import json
import pathlib
import collections

LOG = pathlib.Path("runs/r411-gs.jsonl")

rows = []
for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("dir") == "in" and r.get("kind") == "inband":
        rows.append(r)

print("  inband rows:", len(rows))


def candidate_keys(raw: bytes):
    out = []
    for i in range(0, len(raw) - 12, 1):
        seg = raw[i:i + 4]
        if seg == raw[i + 4:i + 8] == raw[i + 8:i + 12]:
            out.append((i, seg.hex()))
    return out


keys = collections.Counter()
per_packet = []
for r in rows:
    raw = bytes.fromhex(r.get("body_head", ""))
    if len(raw) < 16:
        continue
    cands = candidate_keys(raw)
    if cands:
        # use the first candidate position
        pos, k = cands[0]
        keys[k] += 1
        per_packet.append((r.get("seq"), pos, k, r.get("messageAck")))

print("  packets with a repeated-4x3 segment: %d / %d" % (len(per_packet), len(rows)))
print()
print("  distinct candidate keys:", len(keys))
for k, n in keys.most_common(12):
    print("    %-10s %4dx" % (k, n))
print()
print("  first 12 packets (seq, offset, key, ack):")
for p in per_packet[:12]:
    print("    seq=%-6s off=%-3d key=%-10s ack=%s" % p)
print()
print("  last 6:")
for p in per_packet[-6:]:
    print("    seq=%-6s off=%-3d key=%-10s ack=%s" % p)

# Is the key constant across packets?
if keys:
    top, cnt = keys.most_common(1)[0]
    print()
    print("  most common key %s covers %d/%d packets" % (top, cnt, len(per_packet)))
