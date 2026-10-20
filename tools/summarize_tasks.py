"""Summarise every business task the client has ever requested across runs.

Scans runs/*/lsg.jsonl for task_request / unhandled_task / candidate_task_reply
and prints a table of (service, task) with the body sizes and how the server
answered. This is the ground truth for which services need implementing.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def reason_field(reason: str, key: str) -> str:
    for part in (reason or "").split():
        if part.startswith(key + "="):
            return part.split("=", 1)[1].rstrip(";")
    return ""


def main() -> int:
    rows = collections.defaultdict(lambda: {"bytes": set(), "runs": set(), "handled": set()})
    runs = sorted((ROOT / "runs").glob("*/lsg.jsonl"))
    for log in runs:
        run = log.parent.name
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            event = obj.get("event")
            reason = obj.get("reason") or ""
            if event == "task_request":
                svc = reason_field(reason, "service")
                task = reason_field(reason, "task")
                nbytes = reason_field(reason, "bytes")
                if svc and task:
                    key = (int(svc), int(task))
                    rows[key]["bytes"].add(nbytes)
                    rows[key]["runs"].add(run)
            elif event in ("candidate_task_reply", "candidate_empty_task_reply",
                           "terminal_task_reply"):
                svc = reason_field(reason, "service")
                task = reason_field(reason, "task")
                if svc and task:
                    rows[(int(svc), int(task))]["handled"].add(event)

    if not rows:
        print("no task requests found")
        return 0
    print(f"{'svc':>4} {'task':>6} {'bytes':>10}  {'runs':>4}  handling")
    print("-" * 72)
    for (svc, task), info in sorted(rows.items()):
        sizes = ",".join(sorted(info["bytes"]))
        handled = ",".join(sorted(info["handled"])) or "UNHANDLED"
        print(f"{svc:>4} {task:>6} {sizes:>10}  {len(info['runs']):>4}  {handled}")
    print()
    print(f"total distinct tasks: {len(rows)}; runs scanned: {len(runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
