"""Dump the bdService task-slot table.

`0x7FA800` (addTask) scans the static slot array at `0xE56FFE0` (stride 0x50) for
an empty slot, so pending tasks live there.  Dumping it before and after a
response shows whether the SDK completes the task and which fields change.

    python tools/dump_task_slots.py
    python tools/dump_task_slots.py --output evidence/....json
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
BASE = 0xE56FFE0
SLOTS = 40
STRIDE = 0x50
DUMP = 0x40


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    slots = []
    try:
        for index in range(SLOTS):
            address = BASE + index * STRIDE
            blob = read(handle, address, DUMP)
            if len(blob) < 4:
                continue
            first = int.from_bytes(blob[0:4], "little")
            if first == 0:
                continue
            slots.append({"index": index, "address": hex(address),
                          "first": hex(first), "bytes": blob.hex()})
    finally:
        sc.k32.CloseHandle(handle)
    row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "base": hex(BASE), "stride": STRIDE, "used": len(slots), "slots": slots}
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
