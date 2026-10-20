"""Print the non-keepalive events from one or more lsg.jsonl logs.

    python tools/show_lsg.py runs/20261022-1604220-min/lsg.jsonl
    python tools/show_lsg.py runs/a/lsg.jsonl runs/b/lsg.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def show(path: Path) -> None:
    print(f"=== {path} ===")
    if not path.is_file():
        print("  missing")
        return
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        event = obj.get("event", "")
        counts[event] = counts.get(event, 0) + 1
        if event == "idle_control":
            continue
        reason = (obj.get("reason") or "")[:90]
        utc = obj.get("utc", "")
        print(f"  {utc} {event} {reason}")
    print("  counts:", counts)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        args = [r"E:\GAME\COD\codol-airedux\319\runs\20261022-1604220-min\lsg.jsonl"]
    for a in args:
        show(Path(a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
