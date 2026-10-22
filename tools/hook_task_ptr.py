"""Record the room-query task object created by `0x7F4411`.

`0x7F43C0` creates a bdService task (`0xB9B230`), stores it in `[ebp-4]`, and
registers the completion callback.  Recording that pointer lets us dump the task
object and see what the SDK stores in it (transaction id, action, state) - the
missing piece for why the task never completes.

    python tools/hook_task_ptr.py --install
    python tools/hook_task_ptr.py --read --dump 0x100
    python tools/hook_task_ptr.py --revert
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
CALL_SITE = 0x7F4411
CALL_TARGET = 0xB9B230
RESUME_VA = 0x7F4416
RING = 8


def open_client():
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    return pid, handle


def alloc(handle, size: int, protect: int) -> int:
    return int(sc.k32.VirtualAllocEx(handle, None, size, 0x3000, protect))


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def build_cave(cave: int, record: int) -> bytes:
    code = bytearray()
    code += bytes([0xE8]) + struct.pack("<i", CALL_TARGET - (cave + 5))
    code += bytes([0x50])                                        # push eax
    code += bytes([0x8B, 0x45, 0xFC])                            # mov eax,[ebp-4]
    code += bytes([0x8B, 0x0D]) + struct.pack("<I", record)      # mov ecx,[record]
    code += bytes([0x41])                                        # inc ecx
    code += bytes([0x89, 0x0D]) + struct.pack("<I", record)      # mov [record],ecx
    code += bytes([0x83, 0xE1, 0x07])                            # and ecx,7
    code += bytes([0xC1, 0xE1, 0x02])                            # shl ecx,2
    code += bytes([0x81, 0xC1]) + struct.pack("<I", record + 4)  # add ecx,record+4
    code += bytes([0x89, 0x01])                                  # mov [ecx],eax
    code += bytes([0x58])                                        # pop eax
    pos = len(code)
    code += b"\xe9\x00\x00\x00\x00"
    struct.pack_into("<i", code, pos + 1, RESUME_VA - (cave + pos + 5))
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--dump", type=lambda v: int(v, 0), default=0x100)
    parser.add_argument("--state", default=str(ROOT / "runs" / "task_ptr_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            same_process = state.get("pid") == pid
            cave = (state.get("cave") if same_process else None) or alloc(handle, 0x200, 0x40)
            record = (state.get("record") if same_process else None) or alloc(handle, 0x100, 0x04)
            sc.w(handle, record, bytes(0x100))
            original = read(handle, CALL_SITE, 5)
            code = build_cave(int(cave), int(record))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            patch = b"\xe9" + struct.pack("<i", int(cave) - (CALL_SITE + 5))
            sc.w(handle, CALL_SITE, patch)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(CALL_SITE), 5)
            readback = read(handle, CALL_SITE, 5)
            row = {"schema": 1, "pid": pid, "cave": int(cave), "record": int(record),
                   "original": original.hex(), "readback": readback.hex(),
                   "verified": readback == patch}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(row, indent=2) + "\n")
            print(json.dumps(row, ensure_ascii=True, indent=2))
            return 0
        state = json.loads(state_path.read_text())
        if args.read:
            data = read(handle, int(state["record"]), 4 + RING * 4)
            count = struct.unpack_from("<I", data, 0)[0]
            pointers = [struct.unpack_from("<I", data, 4 + i * 4)[0] for i in range(RING)]
            pointers = [p for p in pointers if p]
            dumps = []
            for pointer in pointers[-3:]:
                blob = read(handle, pointer, args.dump)
                dumps.append({"task": hex(pointer), "bytes": blob.hex()})
            row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
                   "count": count, "pointers": [hex(p) for p in pointers], "dumps": dumps}
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            sc.w(handle, CALL_SITE, bytes.fromhex(state["original"]))
            sc.k32.FlushInstructionCache(handle, C.c_void_p(CALL_SITE), 5)
            now = read(handle, CALL_SITE, 5)
            print(json.dumps({"reverted": now.hex() == state["original"]}, ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
