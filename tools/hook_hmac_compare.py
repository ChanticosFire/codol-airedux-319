"""Record the client's bdService HMAC comparison inputs.

`0xBA3710` computes a 20-byte HMAC and compares its first 8 bytes with bytes it
read from the message.  This hook copies both sides (and a hit counter) into a
process buffer, then executes the two overwritten instructions and returns.

    python tools/hook_hmac_compare.py --install
    python tools/hook_hmac_compare.py --read
    python tools/hook_hmac_compare.py --revert

Layout of the record buffer (little endian):
    +0x00  16 bytes  computed side   ([ebp-0x2c] .. )
    +0x10  16 bytes  message side    ([ebp-0x18] .. )
    +0x20  u32       hit count
    +0x24  u32       message length  ([ebp+0xc] if valid)
    +0x28  u32       buffer pointer  ([ebp+0x08] if valid)
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
PATCH_VA = 0xBA398D          # mov eax,[ebp-0x18]; movzx ecx,byte [ebp-0x2b]
PATCH_LEN = 7
RESUME_VA = 0xBA3994
ORIGINAL = bytes.fromhex("8b45e80fb64dd5")
RECORD_MAGIC = 0x484D4143    # "HMAC"


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
    code += b"\x60"                                   # pushad
    for source, dest in ((0x2C, 0x00), (0x18, 0x10)):
        code += b"\x8d\x75" + bytes([0x100 - source])   # lea esi,[ebp-source]
        for index in range(4):
            code += b"\x8b\x06" if index == 0 else b"\x8b\x46" + bytes([index * 4])
            code += b"\xa3" + struct.pack("<I", record + dest + index * 4)
    code += b"\xff\x05" + struct.pack("<I", record + 0x20)   # inc [record+0x20]
    code += b"\x8b\x45\x0c" + b"\xa3" + struct.pack("<I", record + 0x24)
    code += b"\x8b\x45\x08" + b"\xa3" + struct.pack("<I", record + 0x28)
    code += b"\x61"                                   # popad
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
    parser.add_argument("--state", default=str(ROOT / "runs" / "hmac_hook_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            cave = state.get("cave") or alloc(handle, 0x400, 0x40)
            record = state.get("record") or alloc(handle, 0x100, 0x04)
            sc.w(handle, record, bytes(0x40))
            code = build_cave(int(cave), int(record))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            original = read(handle, PATCH_VA, PATCH_LEN)
            patch = b"\xe9" + struct.pack("<i", int(cave) - (PATCH_VA + 5)) + b"\x90\x90"
            sc.w(handle, PATCH_VA, patch)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(PATCH_VA), len(patch))
            readback = read(handle, PATCH_VA, PATCH_LEN)
            state = {"schema": 1, "pid": pid, "cave": int(cave), "record": int(record),
                     "original": original.hex(), "patch": patch.hex(),
                     "readback": readback.hex(), "verified": readback == patch}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=2) + "\n")
            print(json.dumps(state, ensure_ascii=True, indent=2))
            return 0
        state = json.loads(state_path.read_text())
        if args.read:
            data = read(handle, int(state["record"]), 0x40)
            row = {
                "schema": 1, "utc": datetime.now(timezone.utc).isoformat(),
                "pid": pid, "hits": struct.unpack_from("<I", data, 0x20)[0],
                "computed16": data[0:16].hex(), "message16": data[0x10:0x20].hex(),
                "message_len": struct.unpack_from("<I", data, 0x24)[0],
                "buffer_ptr": hex(struct.unpack_from("<I", data, 0x28)[0]),
            }
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            sc.w(handle, PATCH_VA, bytes.fromhex(state["original"]))
            sc.k32.FlushInstructionCache(handle, C.c_void_p(PATCH_VA), PATCH_LEN)
            now = read(handle, PATCH_VA, PATCH_LEN)
            print(json.dumps({"reverted": now.hex() == state["original"],
                              "readback": now.hex()}, ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
