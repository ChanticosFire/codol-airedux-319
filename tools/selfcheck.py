"""One entry point for every self check in this project.

Each check below corresponds to a real problem that cost a session before it was
understood, so keeping them green is the cheapest way to protect the delivered
parts of the server.

Usage:
    python tools/selfcheck.py            # run everything
    python tools/selfcheck.py --list     # list the checks
Exit code 0 means every check passed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(args: list[str], timeout: int = 180) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout)
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode, "\n".join(tail[-3:])


def check_codec() -> tuple[bool, str]:
    code, out = run([PY, "-B", "-X", "utf8", "-m", "server1649370.ps_codec"])
    return code == 0 and "failures: 0" in out, out


def check_encoder_against_client() -> tuple[bool, str]:
    code, out = run([PY, "-B", "-X", "utf8", "tools/verify_encoder.py"])
    return code == 0 and "failures: 0" in out, out


def check_evidence() -> tuple[bool, str]:
    code, out = run([PY, "-B", "-X", "utf8", "tools/check_evidence.py"])
    return code == 0, out


def check_rejects_bad_map() -> tuple[bool, str]:
    code, out = run([PY, "-B", "-X", "utf8", "-m", "server1649370.gameserver",
                     "--port", "28997", "--gamestate-map", "bad/map"])
    return code == 2 and "not a plain map name" in out, out.replace("\n", " ")[-160:]


def check_rejects_missing_snapshot() -> tuple[bool, str]:
    code, out = run([PY, "-B", "-X", "utf8", "-m", "server1649370.gameserver",
                     "--port", "28997", "--snapshot-file", "runs/does-not-exist.bin"])
    return code == 2 and "does not exist" in out, out.replace("\n", " ")[-160:]


def check_rejects_hazard_breakpoint() -> tuple[bool, str]:
    code, out = run([PY, "-B", "-X", "utf8", "tools/launch_1649370.py",
                     "--name", "selfcheck", "--breakpoint", "0x4475f0:Glass"])
    return code == 1 and "hazard" in out.lower(), out.replace("\n", " ")[-160:]


def check_required_files() -> tuple[bool, str]:
    required = [
        "RELEASE.md",
        "docs/RUNBOOK.md",
        "docs/SNAPSHOT-FORMAT.md",
        "docs/PHASE-SUMMARY.md",
        "server1649370/gameserver.py",
        "server1649370/ps_codec.py",
        "server1649370/native_gamestate.py",
        "tools/run_match.py",
        "runs/snapshot-hybrid-empty-actors.bin",
        "runs/snapshot-single22.bin",
    ]
    missing = [name for name in required if not (ROOT / name).exists()]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, f"{len(required)} files present"


def check_runner_summary_has_delivery() -> tuple[bool, str]:
    summary = ROOT / "runs" / "verify-test-summary.json"
    if not summary.exists():
        return True, "no recent run summary to inspect (skipped)"
    data = json.loads(summary.read_text(encoding="utf-8"))
    delivery = data.get("delivery")
    if not isinstance(delivery, dict) or "ok" not in delivery:
        return False, "runner summary has no delivery block"
    return True, f"delivery ok={delivery['ok']} snapshots={delivery.get('snapshots_queued')}"


CHECKS = [
    ("codec round-trip", check_codec),
    ("encoder vs accepted body", check_encoder_against_client),
    ("evidence audit", check_evidence),
    ("reject bad map name", check_rejects_bad_map),
    ("reject missing snapshot", check_rejects_missing_snapshot),
    ("reject hazard breakpoint", check_rejects_hazard_breakpoint),
    ("required files", check_required_files),
    ("runner delivery block", check_runner_summary_has_delivery),
]


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for name, _ in CHECKS:
            print(name)
        return 0

    failures = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as error:                      # noqa: BLE001
            ok, detail = False, f"raised {type(error).__name__}: {error}"
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{status}] {name}: {detail}")

    print(f"\nselfcheck: {len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
