"""Hardlink verified 1649370 loose assets into one existing runtime.

This adds directory entries under runtime/hires without copying resource bytes.
Every source is checked against its original IFS extraction receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMUNITY_RUNS = Path(r"E:\GAME\COD\1649370\workspaces\offline-runs").resolve()
PACKS = {
    "crossfire": ("20261022-crossfire-loose-v461", 538, "images/loadscreen_mp_crossfire.iwi"),
    "gametype": ("20261022-gametype-loose-v461", 1037, "images/dpad_ks_uav.iwi"),
    "crash_tropical": ("20261022-crash-tropical-loose-v461", 1099, "images/sun_flare_icbm.iwi"),
    "survival": ("20261022-survival-loose-v461", 403, "images/wavy_nml.iwi"),
    "dmz": ("20261022-dmz-loose-v461", 223, "images/barrel_d.iwi"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--pack", choices=PACKS, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    library_name, expected_count, probe_name = PACKS[args.pack]
    library = ROOT / "runs" / library_name
    output = args.output or ROOT / f"runs/codex-{args.pack}-loose-links.json"
    runtime = args.runtime.resolve()
    if runtime.name != "runtime" or runtime.parent.parent != COMMUNITY_RUNS:
        raise SystemExit("runtime must be an existing direct child of offline-runs")
    if runtime.is_junction() or runtime.is_symlink():
        raise SystemExit("linked runtime refused")
    receipt = json.loads((library / "receipt.json").read_text(encoding="utf-8"))
    if receipt.get("build") != 1649370 or receipt.get("listed") != expected_count or receipt.get("decoded") != expected_count:
        raise SystemExit(f"{args.pack} extraction receipt is incomplete or wrong version")
    assets = []
    for row in receipt["resources"]:
        member = Path(row["member"])
        if not row["present"] or not member.parts or member.parts[0] != "main" or ".." in member.parts:
            raise SystemExit(f"invalid receipt member: {member}")
        source = library / member
        relative = Path(*member.parts[1:])
        target = runtime / "hires" / relative
        if not source.is_file() or source.is_symlink() or digest(source) != row["decoded_sha256"]:
            raise SystemExit(f"{args.pack} source differs from verified IFS receipt: {source}")
        if target.exists() and (not target.is_file() or digest(target) != row["decoded_sha256"]):
            raise SystemExit(f"existing runtime asset differs: {target}")
        assets.append((source, target))
    created = 0
    for source, target in assets:
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_junction() or target.parent.is_symlink():
            raise SystemExit(f"linked destination parent refused: {target.parent}")
        os.link(source, target)
        created += 1
    probe = runtime / "hires" / probe_name
    if not probe.is_file():
        raise RuntimeError(f"probe asset was not staged: {probe}")
    report = {"schema": 1, "build": 1649370, "pack": args.pack, "runtime": str(runtime),
              "source_receipt": str(library / "receipt.json"), "verified_assets": len(assets),
              "hardlinks_created": created, "shared_bytes": sum(source.stat().st_size for source, _ in assets),
              "probe": probe_name, "probe_sha256": digest(probe)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
