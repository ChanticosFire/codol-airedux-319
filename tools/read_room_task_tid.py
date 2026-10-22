"""Read the client-assigned transaction id of the pending room task.

The bdService task slot table at `0xE56FFE0` (stride 0x50) stores the action at
`+0x00` and a monotonically increasing transaction id at `+0x08`.  The room
query registers action 38 (`0x26`); its slot's `+0x08` value is the id the
response must echo (hypothesis under test).

    python tools/read_room_task_tid.py
    python tools/read_room_task_tid.py --write runs/room_tid.txt
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
BASE = 0xE56FFE0
SLOTS = 40
STRIDE = 0x50


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", type=lambda v: int(v, 0), default=0x26)
    parser.add_argument("--write")
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    found = []
    try:
        for index in range(SLOTS):
            address = BASE + index * STRIDE
            blob = read(handle, address, 0x40)
            if len(blob) < 0x40:
                continue
            action = struct.unpack_from("<I", blob, 0)[0]
            if action != args.action:
                continue
            tid = struct.unpack_from("<I", blob, 0x08)[0]
            found.append({"index": index, "address": hex(address),
                          "tid": tid, "tid_hex": hex(tid),
                          "params": hex(struct.unpack_from("<I", blob, 0x28)[0]),
                          "callback": hex(struct.unpack_from("<I", blob, 0x30)[0])})
    finally:
        sc.k32.CloseHandle(handle)
    row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "action": hex(args.action), "tasks": found}
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    if args.write and found:
        Path(args.write).write_text(str(found[-1]["tid"]) + "\n", encoding="utf-8")
        row["written"] = str(found[-1]["tid"])
    print(json.dumps(row, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
