"""Search the original IFS packs for member paths without extracting them.

An IFS file starts with `nifs`, a small header and the plain-text member list
(`<pack>.lst` followed by CRLF-separated paths).  The list is at the front of
the file, so scanning the first few MiB of every pack is enough to locate a
member and its owning pack.

    python tools/find_ifs_members.py spark_atlas.iwi glow_org.iwi
    python tools/find_ifs_members.py --out runs/ifs-member-search.json --list
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE_ROOT = Path(r"E:\GAME\COD\Original Client\IIPS\IIPSDownload")
SCAN_BYTES = 4 * 1024 * 1024


def scan_pack(path: Path, needles: list[bytes]) -> dict[str, str]:
    hits: dict[str, str] = {}
    with path.open("rb") as stream:
        data = stream.read(SCAN_BYTES)
    lower = data.lower()
    start = lower.find(b".lst")
    if start < 0:
        return hits
    # member list ends at the first NUL-heavy binary region; scan lines
    end = lower.find(b"\r\n\r\n", start)
    block = data[start:end if end > 0 else len(data)]
    for line in block.split(b"\r\n"):
        if not line or len(line) > 512:
            continue
        try:
            text = line.decode("ascii")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        for needle in needles:
            if needle in lowered:
                hits[needle] = text
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*", help="member basenames or path fragments")
    parser.add_argument("--list", action="store_true", help="list the first 40 members of each pack")
    parser.add_argument("--out", type=Path, default=Path("runs/ifs-member-search.json"))
    args = parser.parse_args()
    needles = [name.lower() for name in args.names]
    packs = sorted(SOURCE_ROOT.glob("*.ifs"))
    print(f"packs={len(packs)} needles={args.names}")
    report = {"source": str(SOURCE_ROOT), "packs": len(packs), "needles": args.names, "hits": {}}
    if args.list:
        for pack in packs[:3]:
            with pack.open("rb") as stream:
                data = stream.read(SCAN_BYTES)
            start = data.lower().find(b".lst")
            text = data[start:start + 1200].decode("ascii", "replace")
            print("==", pack.name)
            print(text)
        return 0
    for pack in packs:
        try:
            hits = scan_pack(pack, needles)
        except OSError as error:
            print("skip", pack.name, error)
            continue
        if hits:
            report["hits"][pack.name] = hits
            print(pack.name, hits)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("hit packs:", len(report["hits"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
