"""Compare two 1649370 images byte-for-byte and report changed VA ranges.

The repository documents static analysis against the shipped image
(`bin\\v1649370\\codol1649370-offline.exe`, SHA-256 55f067ac...).  The runtime
copy actually launched from `workspaces\\offline-runs\\r107flow\\runtime` has a
different digest, so any static claim must first state which image it came
from.  This tool maps raw offsets to VAs using the shipping image's sections.

    python tools/compare_image_bytes_1649370.py --a <image> --b <image>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pefile

DEFAULT_A = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
DEFAULT_B = Path(
    r"E:\GAME\COD\1649370\workspaces\offline-runs\r107flow\runtime\codol1649370-offline.exe"
)


def sections(image: Path):
    pe = pefile.PE(str(image), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    out = []
    for section in pe.sections:
        out.append({
            "name": section.Name.decode(errors="replace").rstrip("\0"),
            "va": base + section.VirtualAddress,
            "vsize": section.Misc_VirtualSize,
            "raw": section.PointerToRawData,
            "rawsize": section.SizeOfRawData,
        })
    return out


def raw_to_va(secs, offset: int):
    for section in secs:
        start = section["raw"]
        if start <= offset < start + section["rawsize"]:
            return section["va"] + (offset - start), section["name"]
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, default=DEFAULT_A)
    ap.add_argument("--b", type=Path, default=DEFAULT_B)
    ap.add_argument("--gap", type=int, default=8, help="merge ranges separated by <= gap bytes")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    a = args.a.read_bytes()
    b = args.b.read_bytes()
    secs = sections(args.a)
    same_size = len(a) == len(b)
    limit = min(len(a), len(b))
    diff = [i for i in range(limit) if a[i] != b[i]]
    ranges: list[list[int]] = []
    for index in diff:
        if ranges and index - ranges[-1][1] <= args.gap:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])

    report = {
        "a": str(args.a),
        "a_sha256": hashlib.sha256(a).hexdigest(),
        "b": str(args.b),
        "b_sha256": hashlib.sha256(b).hexdigest(),
        "sizes": [len(a), len(b)],
        "same_size": same_size,
        "changed_bytes": len(diff),
        "range_count": len(ranges),
        "ranges": [],
    }
    for start, end in ranges:
        va, name = raw_to_va(secs, start)
        entry = {
            "raw": [start, end],
            "length": end - start + 1,
            "section": name,
            "va": va,
            "a_hex": a[start:end + 1].hex(),
            "b_hex": b[start:end + 1].hex(),
        }
        report["ranges"].append(entry)
    print(json.dumps({k: v for k, v in report.items() if k != "ranges"}, indent=2))
    for entry in report["ranges"][: args.show]:
        print(f"raw {entry['raw'][0]:#08x}-{entry['raw'][1]:#08x} "
              f"len={entry['length']} va={entry['va'] and hex(entry['va'])} "
              f"sec={entry['section']}")
        print(f"  A {entry['a_hex']}")
        print(f"  B {entry['b_hex']}")
        if entry["length"] <= 32:
            print("  A_i { " + ", ".join(
                f"{int(entry['a_hex'][i:i + 2], 16):#04x}"
                for i in range(0, len(entry["a_hex"]), 2)) + " }")
            print("  B_i { " + ", ".join(
                f"{int(entry['b_hex'][i:i + 2], 16):#04x}"
                for i in range(0, len(entry["b_hex"]), 2)) + " }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
