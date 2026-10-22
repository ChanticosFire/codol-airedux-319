"""Inject one decoded room record into the frontend room list model.

The room-query result handler ends in `0x637590`, which copies `count * 0x238`
bytes into the frontend room object `[0x82E13FC] + 0x7470` and stores the count
at `+0x7230`.  Since the SDK never completes the task, this tool performs the
same copy by hand from the already-decoded record object, so the list widget has
data to render.

    python tools/write_room_list_entry.py            # inject
    python tools/write_room_list_entry.py --revert   # clear the list
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
ROOM_GLOBAL = 0x82E13FC
COUNT_OFFSET = 0x7230
LIST_OFFSET = 0x7470
ENTRY_SIZE = 0x238
RECORD_SIZE = 0x228


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=lambda v: int(v, 0), default=None,
                        help="record object address; default: find 'AI-Room'")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid}
    try:
        room = sc.u32(handle, ROOM_GLOBAL)
        row["room"] = hex(room)
        if not room:
            raise OSError("frontend room object is null")
        before = read(handle, room + COUNT_OFFSET, 4)
        row["count_before"] = struct.unpack("<I", before)[0] if len(before) == 4 else None
        if args.revert:
            sc.w(handle, room + COUNT_OFFSET, struct.pack("<I", 0))
            row["reverted"] = True
        else:
            record = args.record
            if record is None:
                needle = b"AI-Room"
                base = None
                import find_objects_by_vtable as finder
                for region_base, region_size, _protect in finder.iter_regions(handle):
                    blob = read(handle, region_base, region_size)
                    found = blob.find(needle)
                    if found >= 0:
                        base = region_base + found - 0x128
                        break
                if base is None:
                    raise OSError("decoded record not found in memory")
                record = base
            row["record"] = hex(record)
            payload = read(handle, record, RECORD_SIZE)
            if len(payload) < RECORD_SIZE:
                raise OSError("record read failed")
            slot = payload + bytes(ENTRY_SIZE - RECORD_SIZE)
            sc.w(handle, room + LIST_OFFSET, slot)
            sc.w(handle, room + COUNT_OFFSET, struct.pack("<I", args.count))
            row["wrote_bytes"] = ENTRY_SIZE
        after = read(handle, room + COUNT_OFFSET, 4)
        row["count_after"] = struct.unpack("<I", after)[0] if len(after) == 4 else None
        row["head_after"] = read(handle, room + LIST_OFFSET, 0x20).hex()
    finally:
        sc.k32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
