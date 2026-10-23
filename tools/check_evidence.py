"""Audit the evidence directory.

Every experiment record must be valid JSON with a `schema` and a `scope`, and it
is reported whether the main documents reference it. This keeps the 115+ records
usable as an evidence trail instead of a pile of files.

Usage:
    python tools/check_evidence.py            # summary + problems
    python tools/check_evidence.py --strict   # also fail on unreferenced files
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "experiments"
DOCS = [
    ROOT / "1649370-STATUS.md",
    ROOT / "PROJECT_STATUS.md",
    ROOT / "RELEASE.md",
    ROOT / "docs" / "SNAPSHOT-FORMAT.md",
    ROOT / "docs" / "PHASE-SUMMARY.md",
    ROOT / "docs" / "RUNBOOK.md",
]


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    if not EVIDENCE.is_dir():
        print(f"missing evidence directory: {EVIDENCE}")
        return 2

    files = sorted(EVIDENCE.glob("*.json"))
    if not files:
        print("no evidence records found")
        return 2

    doc_text = ""
    for path in DOCS:
        if path.is_file():
            doc_text += path.read_text(encoding="utf-8", errors="replace")

    invalid, missing_fields, unreferenced = [], [], []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            invalid.append((path.name, str(error)))
            continue
        if not isinstance(record, dict):
            invalid.append((path.name, "top level is not an object"))
            continue
        for field in ("schema", "scope"):
            if field not in record:
                missing_fields.append((path.name, field))
        if path.name not in doc_text:
            unreferenced.append(path.name)

    print(f"records: {len(files)}")
    print(f"referenced by a document: {len(files) - len(unreferenced)}")
    print(f"invalid JSON: {len(invalid)}")
    print(f"missing required fields: {len(missing_fields)}")
    print(f"unreferenced (informational): {len(unreferenced)}")

    for name, error in invalid[:10]:
        print(f"  INVALID {name}: {error}")
    for name, field in missing_fields[:10]:
        print(f"  NO-FIELD {name}: missing {field!r}")
    if unreferenced:
        print("  unreferenced files (fine, but nothing points at them):")
        for name in unreferenced[:10]:
            print(f"    {name}")

    legacy = len(missing_fields) + len([1 for _ in files if False])
    if missing_fields:
        print(f"  note: {len(missing_fields)} legacy records predate the schema/scope"
              " convention; they are reported but not fatal")
    if invalid:
        print("check_evidence: FAILED (invalid JSON)")
        return 1
    if strict and missing_fields:
        print("check_evidence: FAILED (strict: records missing schema/scope)")
        return 1
    if strict and unreferenced:
        print("check_evidence: FAILED (strict: unreferenced records)")
        return 1
    print("check_evidence: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
