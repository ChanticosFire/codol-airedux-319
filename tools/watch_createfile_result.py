"""Poll the 1649370 CreateFileA result ring before pointers become stale."""
from __future__ import annotations

import argparse
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import hook_createfile as base
import hook_createfile_result as hook
import start_conn as sc


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=25)
    parser.add_argument("--interval-ms", type=int, default=20)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.seconds <= 0 or args.interval_ms < 5:
        parser.error("seconds must be positive and interval-ms at least 5")
    state = json.loads(hook.STATE.read_text(encoding="utf-8"))
    pid, handle = base.open_client()
    if pid != state["pid"]:
        raise ValueError("installed CreateFileA result hook belongs to a different process")
    record = int(state["record"], 0)
    rows = []
    seen = 0
    lost = 0
    stopped = "time_limit"
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            raw = base.read(handle, record, 0x10 + hook.COUNT * hook.STRIDE)
            if len(raw) != 0x10 + hook.COUNT * hook.STRIDE:
                stopped = "process_memory_unavailable"
                break
            count = struct.unpack_from("<I", raw, 0)[0]
            if count < seen:
                stopped = "ring_counter_reset"
                break
            first = max(seen, count - hook.COUNT)
            lost += first - seen
            for sequence in range(first, count):
                offset = 0x10 + (sequence & (hook.COUNT - 1)) * hook.STRIDE
                caller, pointer, result, error = struct.unpack_from("<IIII", raw, offset)
                name_data = base.read(handle, pointer, 260) if pointer else b""
                name = name_data.split(b"\0", 1)[0].decode("latin-1", "replace")
                rows.append({"sequence": sequence, "utc": now(), "caller": hex(caller),
                             "name_ptr": hex(pointer), "name": name,
                             "handle": hex(result), "last_error": error,
                             "failed": result == 0xFFFFFFFF})
            seen = count
            time.sleep(args.interval_ms / 1000)
    finally:
        sc.k32.CloseHandle(handle)
    report = {"schema": 1, "build": 1649370, "pid": pid,
              "started_hook_utc": state["utc"], "watch_end_utc": now(),
              "interval_ms": args.interval_ms, "stopped": stopped,
              "observed_count": len(rows), "ring_count": seen,
              "lost_sequences": lost, "entries": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "entries"},
                     ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
