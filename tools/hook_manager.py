"""Record the bdService manager pointer and action at `0x7FA800` entry.

`0x7FAA20` forwards to `0x7FA800(this=manager, action, ...)`; recording `ecx`
and `[ebp+8]` gives us the manager object that owns the pending task list, so we
can dump it and see whether the room query task is still queued after a reply.

    python tools/hook_manager.py --install
    python tools/hook_manager.py --read
    python tools/hook_manager.py --revert
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
HOOK_VA = 0x7FA800
ORIGINAL = bytes.fromhex("55 8b ec 83 ec 54")
RESUME_VA = 0x7FA806


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
    code = bytearray(b"\x60")                                    # pushad
    code += bytes([0xFF, 0x05]) + struct.pack("<I", record)      # inc [record]
    code += bytes([0x89, 0x0D]) + struct.pack("<I", record + 4)  # mov [rec+4],ecx
    code += bytes([0x8B, 0x45, 0x08])                            # mov eax,[ebp+8]
    code += bytes([0xA3]) + struct.pack("<I", record + 8)        # mov [rec+8],eax
    code += bytes([0x8B, 0x45, 0x0C])                            # mov eax,[ebp+0xc]
    code += bytes([0xA3]) + struct.pack("<I", record + 0x0C)     # mov [rec+0xc],eax
    code += bytes([0x61])                                        # popad
    code += ORIGINAL
    code += bytes([0xE9]) + struct.pack("<i", RESUME_VA - (cave + len(code) + 5))
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--dump", type=lambda v: int(v, 0), default=0x100)
    parser.add_argument("--state", default=str(ROOT / "runs" / "manager_hook_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            same_process = state.get("pid") == pid
            cave = (state.get("cave") if same_process else None) or alloc(handle, 0x200, 0x40)
            record = (state.get("record") if same_process else None) or alloc(handle, 0x40, 0x04)
            sc.w(handle, record, bytes(0x40))
            original = read(handle, HOOK_VA, len(ORIGINAL))
            code = build_cave(int(cave), int(record))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            patch = b"\xe9" + struct.pack("<i", int(cave) - (HOOK_VA + 5)) + b"\x90"
            sc.w(handle, HOOK_VA, patch)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(HOOK_VA), len(patch))
            readback = read(handle, HOOK_VA, len(patch))
            row = {"schema": 1, "pid": pid, "cave": int(cave), "record": int(record),
                   "original": original.hex(), "readback": readback.hex(),
                   "verified": readback == patch}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(row, indent=2) + "\n")
            print(json.dumps(row, ensure_ascii=True, indent=2))
            return 0
        state = json.loads(state_path.read_text())
        if args.read:
            data = read(handle, int(state["record"]), 0x10)
            hits, manager, action, arg2 = struct.unpack_from("<IIII", data, 0)
            row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
                   "hits": hits, "manager": hex(manager), "action": action,
                   "arg2": hex(arg2)}
            if manager:
                row["manager_dump"] = read(handle, manager, args.dump).hex()
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            sc.w(handle, HOOK_VA, bytes.fromhex(state["original"]))
            sc.k32.FlushInstructionCache(handle, C.c_void_p(HOOK_VA), len(ORIGINAL))
            now = read(handle, HOOK_VA, len(ORIGINAL))
            print(json.dumps({"reverted": now.hex() == state["original"]}, ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
