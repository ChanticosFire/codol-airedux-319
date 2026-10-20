"""Fail-closed identity check for the recorded client anchors.

Supports two builds:
    1649370  the original research target (runtime/client-1649370)
    1604220  the current work target    (runtime/client-1604220)

The build is detected from the EXE SHA-256, never from a path name, so a
mislabelled directory still fails closed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


#: anchors per build: relative path -> (size, sha256)
BUILDS: dict[int, dict[str, tuple[int, str]]] = {
    1649370: {
        "codoMP_client_shipRetail.exe": (
            7841344, "36997674b18f2896de5e9d755686f6922af10708f355175714058d0a0172b537"),
        "codoMP_client_shipRetailBase.dll": (
            60327992, "ef75220de1d6973f34c7069f5bf211b11bd61520c6c0de1882f7359fa5bc6a20"),
        "IIPS/iips.dll": (
            347704, "72ddb9d15626b5a0a001347da141fb944a9f862db713e01c06a964ec8dc35348"),
        "IIPS/IFS2.dll": (
            601656, "5b0324e0b2ba3545a6c02626287d4fbc6a3116594744f4647333982d85508421"),
    },
    1604220: {
        "codoMP_client_shipRetail.exe": (
            7842456, "3da9ef965a65a41bd27d60da1b65fa14ee77ec278eb61624111142c8b1b2e85f"),
        "codoMP_client_shipRetailBase.dll": (
            61137048, "7bbc5fb07ebca9b4671ec0e9a953bbd4e1baaca6a9ca29888531c3213e400f64"),
        "IIPS/iips.dll": (
            347704, "72ddb9d15626b5a0a001347da141fb944a9f862db713e01c06a964ec8dc35348"),
        "IIPS/IFS2.dll": (
            601656, "5b0324e0b2ba3545a6c02626287d4fbc6a3116594744f4647333982d85508421"),
    },
}

#: default build id for callers that only need a label
BUILD = 1649370

#: the anchors of BUILD, kept for backwards compatibility
ANCHORS = BUILDS[BUILD]

_EXE = "codoMP_client_shipRetail.exe"


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


def detect_build(root: Path) -> int:
    """Return the build id whose EXE hash matches, or 0 when unknown."""
    exe = Path(root) / _EXE
    if not exe.is_file():
        return 0
    size = exe.stat().st_size
    digest = None
    for build, anchors in BUILDS.items():
        want_size, want_hash = anchors[_EXE]
        if size != want_size:
            continue
        if digest is None:
            digest = sha256_file(exe)
        if digest == want_hash:
            return build
    return 0


def verify_client(root: Path) -> tuple[Check, ...]:
    """Verify the four anchors of whichever build this directory actually is."""
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("client root is not a directory")
    build = detect_build(root)
    if build == 0:
        raise ValueError("client root matches no recorded build (EXE hash unknown)")
    anchors = BUILDS[build]
    results = []
    for rel, (size, expected_hash) in anchors.items():
        path = root.joinpath(*rel.split("/"))
        if not path.is_file():
            results.append(Check(rel, size, None, expected_hash, None, False, "missing"))
            continue
        actual_size = path.stat().st_size
        if actual_size != size:
            results.append(Check(rel, size, actual_size, expected_hash, None,
                                 False, "size_mismatch"))
            continue
        actual_hash = sha256_file(path)
        ok = actual_hash == expected_hash
        results.append(Check(rel, size, actual_size, expected_hash, actual_hash,
                             ok, "ok" if ok else "sha256_mismatch"))
    return tuple(results)
