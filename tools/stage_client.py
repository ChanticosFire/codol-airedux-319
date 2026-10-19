"""Create a verified, independent Build 1649370 client copy without deleting data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    source = args.source.resolve(strict=True)
    destination = args.destination.resolve()
    workspace = Path(__file__).resolve().parents[1]
    allowed_root = workspace / "runtime"
    if str(source) != str(Path(inventory["client"]).resolve(strict=True)):
        parser.error("source is not the inventoried client")
    if destination == source or source in destination.parents:
        parser.error("destination must be outside the original client")
    if allowed_root not in destination.parents:
        parser.error(f"destination must be a new child of {allowed_root}")
    if destination.exists():
        parser.error("destination already exists; no overwrite or resume is performed")
    if inventory["only_local"] or inventory["only_archive"] or inventory["mismatches"]:
        parser.error("inventory has unresolved differences")

    files = inventory["files"]
    destination.mkdir(parents=True)
    receipt_path = destination.parent / f"{destination.name}.stage-receipt.json"
    receipt = {
        "schema_version": 1,
        "source": str(source),
        "destination": str(destination),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "expected_files": len(files),
        "verified_files": 0,
        "status": "copying",
    }

    def save() -> None:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        for relative, expected in files.items():
            src = source.joinpath(*relative.split("/"))
            dst = destination.joinpath(*relative.split("/"))
            if not src.is_file() or src.stat().st_size != expected["size"]:
                raise ValueError(f"source changed: {relative}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if dst.stat().st_size != expected["size"] or sha256_file(dst) != expected["sha256"]:
                raise ValueError(f"copy verification failed: {relative}")
            receipt["verified_files"] += 1
            if receipt["verified_files"] % 50 == 0:
                save()
        receipt["status"] = "verified"
        receipt["completed_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        print(json.dumps({"status": "verified", "files": len(files), "destination": str(destination)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        receipt["status"] = "incomplete"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        save()
        print(receipt["error"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
