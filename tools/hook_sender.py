"""Record who sends a bdService message.

`0xBA3370` is the virtual "send service message" method (it pushes the inner
type 0x86 and calls the frame builder).  Hooking its entry tells us which engine
function issues a given request - for the room browser that is the `21/13`
query builder.

    python tools/hook_sender.py --install
    python tools/hook_sender.py --read
    python tools/hook_sender.py --revert

Ring entry layout (8 entries, 64 bytes each, at record+0x10):
    +0x00 u32 return address into the caller
    +0x04 u32 first stack argument ([ebp+8])
    +0x08 u32 second stack argument ([ebp+0xc])
    +0x10 48 bytes: EBP chain return addresses (12 dwords)
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
HOOK_VA = 0xBA3370
ORIGINAL = bytes.fromhex("55 8b ec 6a ff")     # push ebp; mov ebp,esp; push -1
RESUME_VA = 0xBA3375
RING_ENTRIES = 8
ENTRY_SIZE = 0x40


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
    entries = record + 0x10
    code = bytearray(b"\x60")                                   # pushad
    code += bytes([0x8B, 0x05]) + struct.pack("<I", record)     # mov eax,[record]
    code += bytes([0x8D, 0x48, 0x01])                           # lea ecx,[eax+1]
    code += bytes([0x89, 0x0D]) + struct.pack("<I", record)     # mov [record],ecx
    code += bytes([0x83, 0xE0, 0x07])                           # and eax,7
    code += bytes([0xC1, 0xE0, 0x06])                           # shl eax,6
    code += bytes([0x05]) + struct.pack("<I", entries)          # add eax,entries
    code += bytes([0x8B, 0x4C, 0x24, 0x20])                     # mov ecx,[esp+0x20]
    code += bytes([0x89, 0x08])                                 # mov [eax],ecx
    code += bytes([0x8B, 0x4C, 0x24, 0x24])                     # mov ecx,[esp+0x24]
    code += bytes([0x89, 0x48, 0x04])                           # mov [eax+4],ecx
    code += bytes([0x8B, 0x4C, 0x24, 0x28])                     # mov ecx,[esp+0x28]
    code += bytes([0x89, 0x48, 0x08])                           # mov [eax+8],ecx
    # walk EBP chain into entry+0x10
    code += bytes([0x89, 0xEE])                                 # mov esi,ebp
    code += bytes([0x8D, 0x78, 0x10])                           # lea edi,[eax+0x10]
    code += bytes([0xB9, 0x0C, 0x00, 0x00, 0x00])               # mov ecx,12
    code += bytes([0x85, 0xF6])                                 # loop: test esi,esi
    code += bytes([0x74, 0x0D])                                 # jz done
    code += bytes([0x8B, 0x56, 0x04])                           # mov edx,[esi+4]
    code += bytes([0x89, 0x17])                                 # mov [edi],edx
    code += bytes([0x8B, 0x36])                                 # mov esi,[esi]
    code += bytes([0x83, 0xC7, 0x04])                           # add edi,4
    code += bytes([0x49])                                       # dec ecx
    code += bytes([0x75, 0xEF])                                 # jnz loop
    code += bytes([0x61])                                       # popad
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
    parser.add_argument("--state", default=str(ROOT / "runs" / "sender_hook_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            same_process = state.get("pid") == pid
            cave = (state.get("cave") if same_process else None) or alloc(handle, 0x300, 0x40)
            record = (state.get("record") if same_process else None) or alloc(handle, 0x300, 0x04)
            sc.w(handle, record, bytes(0x300))
            original = read(handle, HOOK_VA, len(ORIGINAL))
            code = build_cave(int(cave), int(record))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            patch = b"\xe9" + struct.pack("<i", int(cave) - (HOOK_VA + 5))
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
            data = read(handle, int(state["record"]), 0x10 + RING_ENTRIES * ENTRY_SIZE)
            count = struct.unpack_from("<I", data, 0)[0]
            entries = []
            for index in range(RING_ENTRIES):
                base = 0x10 + index * ENTRY_SIZE
                if base + ENTRY_SIZE > len(data):
                    break
                ret, arg0, arg1 = struct.unpack_from("<III", data, base)
                if ret == 0:
                    continue
                chain = struct.unpack_from("<IIIIIIIIIIII", data, base + 0x10)
                entries.append({"index": (index - count) % RING_ENTRIES,
                                "ret": hex(ret), "arg0": hex(arg0), "arg1": hex(arg1),
                                "chain": [hex(v) for v in chain if v]})
            row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(),
                   "pid": pid, "total": count, "entries": entries}
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            sc.w(handle, HOOK_VA, bytes.fromhex(state["original"]))
            sc.k32.FlushInstructionCache(handle, C.c_void_p(HOOK_VA), 7)
            now = read(handle, HOOK_VA, 7)
            print(json.dumps({"reverted": now.hex() == state["original"]}, ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
