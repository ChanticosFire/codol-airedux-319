"""Record what the 1649370 bdService dispatcher receives.

`0xBA39E7` is the success path of the 0x85 business-message parser: it loads the
message pointer/length and calls the dispatcher through `[conn+0x608]`.  This
hook records those values plus the first 64 bytes of the message and a hit
counter, then executes the overwritten `mov esi,[ebp-0x390]` and returns.

    python tools/hook_dispatch.py --install
    python tools/hook_dispatch.py --read
    python tools/hook_dispatch.py --revert

Record layout:
    +0x00 u32 hits
    +0x04 u32 length      ([ebp-0x390])
    +0x08 u32 pointer     ([ebp-0x3b0])
    +0x0C u32 [ebp-0x3a4]
    +0x10 u32 [ebp-0x3ac]
    +0x14 u32 dispatcher  ([edi+0x608])
    +0x40 64 bytes of the message
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
HOOK_VA = 0xBA39E7
HOOK_LEN = 6
ORIGINAL = bytes.fromhex("8bb570fcffff")     # mov esi,[ebp-0x390]
RESUME_VA = 0xBA39ED


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
    def mov_eax_ebp(disp: int) -> bytes:
        return b"\x8b\x85" + struct.pack("<i", disp)

    def store_eax(dest: int) -> bytes:
        return b"\xa3" + struct.pack("<I", dest)

    code = bytearray(b"\x60")                              # pushad
    code += b"\xff\x05" + struct.pack("<I", record)        # inc [record]
    for disp, dest in ((-0x390, 0x04), (-0x3B0, 0x08),
                       (-0x3A4, 0x0C), (-0x3AC, 0x10)):
        code += mov_eax_ebp(disp) + store_eax(record + dest)
    code += b"\x8b\x87\x08\x06\x00\x00"                    # mov eax,[edi+0x608]
    code += store_eax(record + 0x14)
    code += b"\x8b\x95" + struct.pack("<i", -0x390)        # mov edx,[ebp-0x390]
    code += b"\xb9\x40\x00\x00\x00"                        # mov ecx,0x40
    code += b"\x39\xd1"                                    # cmp ecx,edx
    code += b"\x7e\x02"                                    # jle +2
    code += b"\x89\xd1"                                    # mov ecx,edx
    code += b"\x8b\xb5" + struct.pack("<i", -0x3B0)        # mov esi,[ebp-0x3b0]
    code += b"\xbf" + struct.pack("<I", record + 0x40)     # mov edi,record+0x40
    code += b"\xf3\xa4"                                    # rep movsb
    code += b"\x61"                                        # popad
    code += ORIGINAL
    pos = len(code)
    code += b"\xe9\x00\x00\x00\x00"
    struct.pack_into("<i", code, pos + 1, RESUME_VA - (cave + pos + 5))
    return bytes(code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--state", default=str(ROOT / "runs" / "dispatch_hook_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            same_process = state.get("pid") == pid
            cave = (state.get("cave") if same_process else None) or alloc(handle, 0x400, 0x40)
            record = (state.get("record") if same_process else None) or alloc(handle, 0x100, 0x04)
            sc.w(handle, record, bytes(0x80))
            code = build_cave(int(cave), int(record))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            original = read(handle, HOOK_VA, HOOK_LEN)
            patch = b"\xe9" + struct.pack("<i", int(cave) - (HOOK_VA + 5)) + b"\x90"
            sc.w(handle, HOOK_VA, patch)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(HOOK_VA), len(patch))
            readback = read(handle, HOOK_VA, HOOK_LEN)
            state = {"schema": 1, "pid": pid, "cave": int(cave), "record": int(record),
                     "original": original.hex(), "patch": patch.hex(),
                     "readback": readback.hex(), "verified": readback == patch}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=2) + "\n")
            print(json.dumps(state, ensure_ascii=True, indent=2))
            return 0
        state = json.loads(state_path.read_text())
        if args.read:
            data = read(handle, int(state["record"]), 0x80)
            row = {
                "schema": 1, "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
                "hits": struct.unpack_from("<I", data, 0x00)[0],
                "length": struct.unpack_from("<I", data, 0x04)[0],
                "pointer": hex(struct.unpack_from("<I", data, 0x08)[0]),
                "field_3a4": hex(struct.unpack_from("<I", data, 0x0C)[0]),
                "field_3ac": hex(struct.unpack_from("<I", data, 0x10)[0]),
                "dispatcher": hex(struct.unpack_from("<I", data, 0x14)[0]),
                "message_head": data[0x40:0x80].hex(),
            }
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            sc.w(handle, HOOK_VA, bytes.fromhex(state["original"]))
            sc.k32.FlushInstructionCache(handle, C.c_void_p(HOOK_VA), HOOK_LEN)
            now = read(handle, HOOK_VA, HOOK_LEN)
            print(json.dumps({"reverted": now.hex() == state["original"],
                              "readback": now.hex()}, ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
