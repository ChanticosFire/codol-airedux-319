"""Fail-closed identity check for the four recorded Build 1649370 anchors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


BUILD = 1649370
ANCHORS = {
    "codoMP_client_shipRetail.exe": (7841344, "36997674b18f2896de5e9d755686f6922af10708f355175714058d0a0172b537"),
    "codoMP_client_shipRetailBase.dll": (60327992, "ef75220de1d6973f34c7069f5bf211b11bd61520c6c0de1882f7359fa5bc6a20"),
    "IIPS/iips.dll": (347704, "72ddb9d15626b5a0a001347da141fb944a9f862db713e01c06a964ec8dc35348"),
    "IIPS/IFS2.dll": (601656, "5b0324e0b2ba3545a6c02626287d4fbc6a3116594744f4647333982d85508421"),
}


@dataclass(frozen=True)
class Check:
    path: str
    expected_size: int
    actual_size: int | None
    expected_sha256: str
    actual_sha256: str | None
    ok: bool
    reason: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_client(root: Path) -> tuple[Check, ...]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("client root is not a directory")
    results = []
    for rel, (size, expected_hash) in ANCHORS.items():
        path = root.joinpath(*rel.split("/"))
        if not path.is_file():
            results.append(Check(rel, size, None, expected_hash, None, False, "missing"))
            continue
        actual_size = path.stat().st_size
        if actual_size != size:
            results.append(Check(rel, size, actual_size, expected_hash, None, False, "size_mismatch"))
            continue
        actual_hash = sha256_file(path)
        ok = actual_hash == expected_hash
        results.append(Check(rel, size, actual_size, expected_hash, actual_hash,
                             ok, "ok" if ok else "sha256_mismatch"))
    return tuple(results)
