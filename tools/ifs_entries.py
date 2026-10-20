"""Locate every embedded ff payload in an IFS container.

An IFS pack starts with `nifs`, a plain-text entry list (name + CRLF) and then
the concatenated ff payloads, each beginning with the magic `IWff0100`.
Scanning for that magic gives the offsets; the u32 right after it looks like a
size and can be cross-checked against the gap to the next magic.

    python tools/ifs_entries.py <pack.ifs>
    python tools/ifs_entries.py <pack.ifs> --extract mp_playlists --out out.ff
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MAGIC = b"IWff0100"
DEFAULT_PACK = (Path(r"E:\GAME\COD\codol-airedux\319\runtime\client-1604220")
                / "IIPS" / "IIPSDownload" / "ff_init_common_gfx_V106.ifs")


def parse_names(data: bytes) -> list[str]:
    """The entry list is CRLF separated ASCII right after the header."""
    start = data.find(b".lst\r\n")
    if start < 0:
        return []
    start += len(b".lst\r\n")
    end = data.find(b"\r\n\r\n", start)
    block = data[start:end if end > 0 else start + 0x1000]
    names = []
    for line in block.split(b"\r\n"):
        if not line:
            continue
        # stop once the CRLF-separated name list turns into binary (hashes)
        try:
            text = line.decode("ascii")
        except UnicodeDecodeError:
            break
        if any(ord(c) < 0x20 or ord(c) > 0x7E for c in text):
            break
        names.append(text)
    return names


def find_payloads(data: bytes) -> list[tuple[int, int]]:
    """Return (offset_of_magic, declared_size) for every ff payload."""
    out = []
    pos = data.find(MAGIC)
    while pos >= 0:
        size = struct.unpack_from("<I", data, pos + 8)[0] if pos + 12 <= len(data) else 0
        out.append((pos, size))
        pos = data.find(MAGIC, pos + 1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", nargs="?", default=str(DEFAULT_PACK))
    parser.add_argument("--extract", help="entry name substring to write out")
    parser.add_argument("--out", help="output path for --extract")
    args = parser.parse_args()

    path = Path(args.pack)
    if not path.is_file():
        print(f"missing pack: {path}", file=sys.stderr)
        return 2
    data = path.read_bytes()
    names = parse_names(data)
    payloads = find_payloads(data)
    print(f"pack {path.name} ({len(data):,} B)")
    print(f"entry list: {len(names)} names")
    for i, name in enumerate(names):
        print(f"  [{i}] {name}")
    print(f"ff payloads: {len(payloads)}")
    for i, (off, size) in enumerate(payloads):
        print(f"  [{i}] off={off:#x} size_field={size:#x} ({size})")

    if args.extract:
        idx = next((i for i, n in enumerate(names)
                    if args.extract.lower() in n.lower()), None)
        if idx is None:
            print(f"no entry matching {args.extract!r}", file=sys.stderr)
            return 3
        if idx >= len(payloads):
            print(f"entry [{idx}] has no corresponding payload", file=sys.stderr)
            return 4
        start = payloads[idx][0]
        end = payloads[idx + 1][0] if idx + 1 < len(payloads) else len(data)
        blob = data[start:end]
        out = Path(args.out or f"{Path(names[idx]).name}")
        out.write_bytes(blob)
        print(f"extracted [{idx}] {names[idx]} -> {out} ({len(blob):,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
