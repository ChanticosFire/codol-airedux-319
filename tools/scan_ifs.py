"""Scan IFS resource packs for a filename string.

IFS archives usually keep entry names as plain text in their index, so a
substring search over the head of each pack finds which archive holds a file
without needing a full extractor.

    python tools/scan_ifs.py mp_playlists
    python tools/scan_ifs.py rankIconTable --head 8
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CLIENT = Path(r"E:\GAME\COD\codol-airedux\319\runtime\client-1604220")
IFS_ROOT = CLIENT / "IIPS" / "IIPSDownload"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("needle")
    parser.add_argument("--head", type=int, default=4,
                        help="megabytes of each pack to scan (index is usually early)")
    parser.add_argument("--root", default=str(IFS_ROOT))
    args = parser.parse_args()

    needle = args.needle.encode("latin1", "replace")
    root = Path(args.root)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    packs = sorted(root.glob("*.ifs"))
    print(f"scanning {len(packs)} packs for {args.needle!r} "
          f"(first {args.head} MB each)")
    hits = 0
    for pack in packs:
        try:
            with pack.open("rb") as stream:
                data = stream.read(args.head * 1024 * 1024)
        except OSError:
            continue
        if needle in data:
            off = data.find(needle)
            print(f"HIT {pack.name} ({pack.stat().st_size:,} B) at offset {off:#x}")
            # show a little context
            start = max(0, off - 40)
            context = data[start:off + 80]
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in context)
            print(f"     ...{text}...")
            hits += 1
    print(f"done, {hits} pack(s) contain the string")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
