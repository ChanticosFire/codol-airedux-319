"""Count calls to a target function by hooking one `call rel32` site.

The 1649370 state-3 frame dispatch calls the bdService parser at `0xBA3710`
from `0xBA46C2` (`call 0xBA3710`).  Patching that 5-byte call with a jump to a
cave lets us count how often the business parser is entered, which separates
"frame rejected before the parser" from "parser entered but rejected later".

    python tools/hook_call_count.py --install --site 0xba46c2 --target 0xba3710
    python tools/hook_call_count.py --read
    python tools/hook_call_count.py --revert
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


def build_cave(cave: int, record: int, site: int, target: int) -> bytes:
    code = bytearray(b"\x60")                          # pushad
    code += b"\xff\x05" + struct.pack("<I", record)    # inc [record]
    code += b"\x61"                                    # popad
    code += b"\xe8" + struct.pack("<i", target - (cave + len(code) + 5))
    code += b"\xe9" + struct.pack("<i", (site + 5) - (cave + len(code) + 5))
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--site", type=lambda v: int(v, 0), default=0xBA46C2)
    parser.add_argument("--target", type=lambda v: int(v, 0), default=0xBA3710)
    parser.add_argument("--state", default=str(ROOT / "runs" / "call_hook_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            same_process = state.get("pid") == pid and state.get("site") == args.site
            cave = (state.get("cave") if same_process else None) or alloc(handle, 0x200, 0x40)
            record = (state.get("record") if same_process else None) or alloc(handle, 0x40, 0x04)
            sc.w(handle, record, bytes(0x10))
            code = build_cave(int(cave), int(record), args.site, args.target)
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            original = read(handle, args.site, 5)
            patch = b"\xe9" + struct.pack("<i", int(cave) - (args.site + 5))
            sc.w(handle, args.site, patch)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(args.site), 5)
            readback = read(handle, args.site, 5)
            row = {"schema": 1, "pid": pid, "site": hex(args.site), "target": hex(args.target),
                   "cave": int(cave), "record": int(record), "original": original.hex(),
                   "patch": patch.hex(), "readback": readback.hex(),
                   "verified": readback == patch}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(row, indent=2) + "\n")
            print(json.dumps(row, ensure_ascii=True, indent=2))
            return 0
        state = json.loads(state_path.read_text())
        if args.read:
            data = read(handle, int(state["record"]), 8)
            row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
                   "hits": struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else None,
                   "site": state["site"], "target": state["target"]}
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            sc.w(handle, int(state["site"], 16), bytes.fromhex(state["original"]))
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(state["site"], 16)), 5)
            now = read(handle, int(state["site"], 16), 5)
            print(json.dumps({"reverted": now.hex() == state["original"], "readback": now.hex()},
                             ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
