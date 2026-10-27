"""Dump the ordered server-command stream of a CODOL 1649370 demo.

A demo records what the real server sent: configstring/dvar updates (`d`),
server commands (`s`), packet markers (`p`), and assorted `r/v/w/f/c` records.
Reading them in file order shows what a real server sends around match start,
which is the part our own server has never reproduced.

    python tools/dump_demo_cmds.py <demo> --out runs/r693-demo-cmds.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

CMD_RE = re.compile(rb"([dpsrvwfc]) (\d+|none)((?: [^\x00]{0,220})?)\x00")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("demo", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit-per-kind", type=int, default=200000)
    args = ap.parse_args()

    data = args.demo.read_bytes()
    rows = []
    kinds = collections.Counter()
    configstring_indices = set()
    for match in CMD_RE.finditer(data):
        kind = match.group(1).decode()
        argument = match.group(2).decode()
        payload = match.group(3).decode("latin-1", "replace")
        kinds[kind] += 1
        if kind == "d" and argument.isdigit():
            configstring_indices.add(int(argument))
        if kinds[kind] <= args.limit_per_kind:
            rows.append({"offset": match.start(), "kind": kind,
                         "argument": argument, "text": payload[:220]})

    command_rows = [row for row in rows if row["kind"] == "s"]
    config_rows = [row for row in rows if row["kind"] == "d"]
    report = {
        "demo": str(args.demo),
        "size": len(data),
        "total_commands": sum(kinds.values()),
        "kinds": dict(kinds),
        "configstring_index_count": len(configstring_indices),
        "configstring_indices_head": sorted(configstring_indices)[:400],
        "server_commands": command_rows[:4000],
        "config_updates_head": config_rows[:2000],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("demo", "size", "total_commands", "kinds",
                       "configstring_index_count")}, indent=1))
    print(f"server_commands={len(command_rows)} config_updates={len(config_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
