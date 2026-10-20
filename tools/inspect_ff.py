"""Inspect an extracted ff payload for readable strings and header layout.

    python tools/inspect_ff.py runtime/extracted/mp_playlists.ff
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                r"E:\GAME\COD\codol-airedux\319\runtime\extracted\mp_playlists.ff")
    data = path.read_bytes()
    print(f"{path.name}: {len(data):,} B")
    print(f"head: {data[:16].hex(' ')}")
    magic = data.find(b"IWff0100")
    print(f"IWff0100 at {magic:#x}" if magic >= 0 else "no IWff0100 magic")
    runs = [(m.start(), m.group(0)) for m in re.finditer(rb"[\x20-\x7e]{6,}", data)]
    print(f"printable runs: {len(runs)}")
    for off, blob in runs[:40]:
        print(f"  {off:#08x}  {blob[:70].decode('latin1')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
