"""Report when the client first sends a UDP probe, relative to endpoint start.

The window for writing 2 closes about 2.5 seconds after Init because the index fills at roughly
two increments per second. If the client's first probe arrives later than that, no reply timing
can help and the capacity must be raised instead. This prints the gap directly.

    python tools/probe_timing.py runs/20261024-edx/lobby_udp.jsonl
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        return 2
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            print(f"{raw}: missing")
            continue
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        up = next((e for e in events if e.get("event") == "endpoint_up"), None)
        incoming = [e for e in events if e.get("event") == "udp_in"]
        replies = [e for e in events if e.get("event") == "udp_reply"]
        echo = [e for e in events if e.get("event") == "udp_echo"]
        start = parse(up.get("utc") if up else None)
        print(f"{path}")
        print(f"  endpoint_up at {up.get('utc') if up else 'n/a'}")
        print(f"  udp_in={len(incoming)}  udp_reply={len(replies)}  udp_echo={len(echo)}")
        if incoming and start:
            first = parse(incoming[0].get("utc"))
            if first:
                gap = (first - start).total_seconds()
                print(f"  first probe arrived {gap:+.1f} s after endpoint_up")
            print(f"  first payload len={incoming[0].get('length')} "
                  f"hex={str(incoming[0].get('hex'))[:40]}")
            if len(incoming) > 1:
                last = parse(incoming[-1].get("utc"))
                if last and first:
                    span = (last - first).total_seconds()
                    rate = len(incoming) / span if span > 0 else 0
                    print(f"  {len(incoming)} probes over {span:.1f} s "
                          f"({rate:.2f}/s)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
