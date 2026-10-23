"""Backfill the 1649370 runtime hires tree from the offline resource libraries.

The client resolves map assets under ``<runtime>/hires/images``,
``<runtime>/hires/sound`` and ``<runtime>/hires/models``.  The libraries keep
the same relative layout under ``main/``; hard links avoid copying bytes.

Verified 2026-10-23: 22718 image links + 18153 sound/model links reduced the
client's CreateFile misses from 7384 to 61.

Usage:
    python tools/backfill_1649370_hires.py \
        --runtime "E:/GAME/COD/1649370/workspaces/offline-runs/<run>/runtime" \
        --image-library "E:/GAME/COD/1649370/resources/v1649370/offline-image-library" \
        --loose-library "E:/GAME/COD/1649370/resources/v1649370/offline-loose-library"
"""
from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateHardLinkW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]
    kernel32.CreateHardLinkW.restype = ctypes.c_bool
else:  # pragma: no cover - the target is Windows only
    kernel32 = None

MAPPING = (
    ("images", "main/images"),
    ("sound", "main/sound"),
    ("models", "main/models"),
)


def link_tree(source: Path, target: Path) -> tuple[int, int, int]:
    created = skipped = failed = 0
    if not source.is_dir():
        return created, skipped, failed
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        destination = target / item.relative_to(source)
        if destination.exists():
            skipped += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if kernel32 and kernel32.CreateHardLinkW(str(destination), str(item), None):
            created += 1
        else:
            failed += 1
    return created, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--image-library", type=Path, required=True)
    parser.add_argument("--loose-library", type=Path, required=True)
    args = parser.parse_args()
    if not args.runtime.is_dir():
        raise SystemExit(f"runtime not found: {args.runtime}")
    totals = [0, 0, 0]
    for subdir, library_subdir in MAPPING:
        library = args.image_library if subdir == "images" else args.loose_library
        source = library / library_subdir
        target = args.runtime / "hires" / subdir
        created, skipped, failed = link_tree(source, target)
        totals = [totals[0] + created, totals[1] + skipped, totals[2] + failed]
        print(f"{subdir:8} created={created:6d} skipped={skipped:5d} failed={failed:4d}")
    print(f"total    created={totals[0]:6d} skipped={totals[1]:5d} failed={totals[2]:4d}")
    return 0 if totals[2] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
