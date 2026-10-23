"""Hardlink the two publisher-verified 1649370 gametype FFs into one runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(r"E:\GAME\COD\1649370\workspaces\offline-runs").resolve()
SOURCE = ROOT / "runs/20261022-gametype-ff-v461"
RECEIPT = SOURCE / "ff_init_common_gametype_mp_V69.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/codex-gametype-ff-staged.json")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if runtime.name != "runtime" or runtime.parent.parent != RUNS or runtime.is_symlink() or runtime.is_junction():
        raise SystemExit("runtime must be one existing offline-runs child")
    stage = runtime / "client_shipretail/chinese"
    if not stage.is_dir() or stage.is_symlink() or stage.is_junction():
        raise SystemExit("missing or linked stage directory")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    members = receipt["members"]
    if len(members) != 2 or {Path(row["name"]).name for row in members} != {
        "common_gametype_mp.ff", "localized_common_gametype_mp.ff"
    }:
        raise SystemExit("unexpected gametype receipt")
    rows = []
    for row in members:
        name = Path(row["name"]).name
        source = SOURCE / name
        target = stage / name
        if row["version"] != 461 or not row["publisher_signature_verified"]:
            raise SystemExit(f"unverified version/signature: {name}")
        if source.is_symlink() or not source.is_file() or digest(source) != row["sha256"]:
            raise SystemExit(f"source differs from signed receipt: {name}")
        if target.is_symlink() or target.is_junction():
            raise SystemExit(f"linked target refused: {name}")
        before = digest(target) if target.is_file() else None
        if before != row["sha256"]:
            temporary = stage / f".{name}.{uuid.uuid4().hex}.candidate"
            try:
                os.link(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        rows.append({"name": name, "before": before, "after": digest(target),
                     "action": "already_current" if before == row["sha256"] else "hardlinked"})
    report = {"schema": 1, "build": 1649370, "runtime": str(runtime),
              "source_receipt": str(RECEIPT), "files": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
