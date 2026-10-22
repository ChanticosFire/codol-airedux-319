"""Observe the room-browser query callback.

`0x7F4330` is the completion callback registered by `0x7F43C0`; it reads the
request params at `[ebp+8]`, the success flag at `[ebp+0xc]`, and then calls the
real handler pointer at `[params+0x40]`.  Recording its invocations tells us
whether the SDK ever completes the `21/13` task and what it passes to the UI.

    python tools/hook_query_cb.py --install
    python tools/hook_query_cb.py --read
    python tools/hook_query_cb.py --revert

Record layout:
    +0x00 u32 hits
    +0x04 u32 params pointer   ([ebp+8])
    +0x08 u32 success flag     ([ebp+0xc])
    +0x0C u32 handler         ([params+0x40])
    +0x10 u32 handler context ([params+0x44])
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
HOOK_VA = 0x7F4330
ORIGINAL = bytes.fromhex("55 8b ec 83 ec 48")
RESUME_VA = 0x7F4336


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
    code = bytearray(b"\x60")                                   # pushad
    code += bytes([0xFF, 0x05]) + struct.pack("<I", record)     # inc [record]
    code += bytes([0x8B, 0x44, 0x24, 0x24])                     # mov eax,[esp+0x24]
    code += bytes([0xA3]) + struct.pack("<I", record + 4)       # mov [rec+4],eax
    code += bytes([0x85, 0xC0])                                 # test eax,eax
    code += bytes([0x74, 0x1A])                                 # jz done
    code += bytes([0x8B, 0x4C, 0x24, 0x28])                     # mov ecx,[esp+0x28]
    code += bytes([0x89, 0x0D]) + struct.pack("<I", record + 8)  # mov [rec+8],ecx
    code += bytes([0x8B, 0x48, 0x40])                           # mov ecx,[eax+0x40]
    code += bytes([0x89, 0x0D]) + struct.pack("<I", record + 0x0C)
    code += bytes([0x8B, 0x48, 0x44])                           # mov ecx,[eax+0x44]
    code += bytes([0x89, 0x0D]) + struct.pack("<I", record + 0x10)
    code += bytes([0x61])                                       # popad
    code += ORIGINAL
    code += b"\xe9" + struct.pack("<i", RESUME_VA - (cave + len(code) + 5))
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--state", default=str(ROOT / "runs" / "query_cb_state.json"))
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
                   "original": original.hex(), "patch": patch.hex(),
                   "readback": readback.hex(), "verified": readback == patch}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(row, indent=2) + "\n")
            print(json.dumps(row, ensure_ascii=True, indent=2))
            return 0
        state = json.loads(state_path.read_text())
        if args.read:
            data = read(handle, int(state["record"]), 0x20)
            hits, params, flag, handler, context = struct.unpack_from("<IIIII", data, 0)
            row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
                   "hits": hits, "params": hex(params), "success": flag,
                   "handler": hex(handler), "context": hex(context)}
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
