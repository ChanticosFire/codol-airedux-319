"""Scan IFS packs for a string at increasing depth, smallest packs first.

Some asset names live well past the index (which sits near the start), so a
2 MB head scan misses them. This walks the packs ordered by size and reads up to
--head MB, so the cheap small packs are exhausted before the large ones.

    python tools/scan_ifs_deep.py "mp/rankIconTable.csv"
    python tools/scan_ifs_deep.py "mp/callsignTitle.csv" --head 8 --limit 300
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

IFS_ROOT = Path(r"E:\GAME\COD\codol-airedux\319\runtime\client-1604220"
                r"\IIPS\IIPSDownload")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("needle")
    parser.add_argument("--head", type=int, default=8, help="megabytes per pack")
    parser.add_argument("--limit", type=int, default=0,
                        help="only the N smallest packs (0 = all)")
    parser.add_argument("--root", default=str(IFS_ROOT))
    args = parser.parse_args()

    needle = args.needle.encode("latin1", "replace")
    root = Path(args.root)
    packs = sorted(root.glob("*.ifs"), key=lambda p: p.stat().st_size)
    if args.limit:
        packs = packs[:args.limit]
    print(f"scanning {len(packs)} packs for {args.needle!r} "
          f"(up to {args.head} MB each, smallest first)")
    hits = 0
    for idx, pack in enumerate(packs, 1):
        try:
            with pack.open("rb") as stream:
                data = stream.read(args.head * 1024 * 1024)
        except OSError:
            continue
        pos = data.find(needle)
        if pos >= 0:
            print(f"HIT {pack.name} ({pack.stat().st_size:,} B) at {pos:#x}")
            start = max(0, pos - 60)
            ctx = data[start:pos + 90]
            print("     " + "".join(chr(b) if 32 <= b < 127 else "." for b in ctx))
            hits += 1
        if idx % 200 == 0:
            print(f"  ... {idx}/{len(packs)}", flush=True)
    print(f"done, {hits} hit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
