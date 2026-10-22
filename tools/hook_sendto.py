"""Ring-record the caller of the client's Winsock `sendto` (UDP).

The LSG frame is written by some engine function; to find the room-browser query
builder we need the return address of the `send` call that carries the
`21/13` request.  This tool replaces the `sendto` IAT slot (0xCA8518) with a cave
that records (return address, buffer, length, first 16 bytes) into a 16-entry
ring, then tail-jumps to the real import.

    python tools/hook_send.py --install
    python tools/hook_send.py --read
    python tools/hook_send.py --revert

Ring layout (base = record):
    +0x00 u32      next index
    +0x10 ..       entries, 32 bytes each:
        +0x00 u32 return address
        +0x04 u32 buffer pointer
        +0x08 u32 length
        +0x10 16 bytes of payload
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
SEND_IAT = 0xCA8518
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


def build_cave(cave: int, record: int, slot: int) -> bytes:
    entries = record + 0x10
    code = bytearray(b"\x60")                                  # pushad
    code += b"\x8b\x05" + struct.pack("<I", record)            # mov eax,[record]
    code += b"\x8d\x48\x01"                                    # lea ecx,[eax+1]
    code += b"\x89\x0d" + struct.pack("<I", record)            # mov [record],ecx
    code += b"\x83\xe0\x07"                                    # and eax,7
    code += b"\xc1\xe0\x06"                                    # shl eax,6
    code += b"\x05" + struct.pack("<I", entries)               # add eax,entries
    code += b"\x8b\x4c\x24\x20"                                # mov ecx,[esp+0x20]
    code += b"\x89\x08"                                        # mov [eax],ecx
    code += b"\x8b\x4c\x24\x28"                                # mov ecx,[esp+0x28]
    code += b"\x89\x48\x04"                                    # mov [eax+4],ecx
    code += b"\x8b\x4c\x24\x2c"                                # mov ecx,[esp+0x2c]
    code += b"\x89\x48\x08"                                    # mov [eax+8],ecx
    code += b"\x8b\x70\x04"                                    # mov esi,[eax+4]
    code += b"\x8d\x78\x10"                                    # lea edi,[eax+0x10]
    code += b"\xb9\x10\x00\x00\x00"                            # mov ecx,0x10
    code += b"\xf3\xa4"                                        # rep movsb
    # walk the EBP chain: ebp -> [ebp] saved, [ebp+4] return address
    code += bytes([0x89, 0xEE])                        # mov esi,ebp
    code += bytes([0x8D, 0x78, 0x20])                  # lea edi,[eax+0x20]
    code += bytes([0xB9, 0x06, 0x00, 0x00, 0x00])      # mov ecx,6
    code += bytes([0x85, 0xF6])                        # loop: test esi,esi
    code += bytes([0x74, 0x0D])                        # jz done
    code += bytes([0x8B, 0x56, 0x04])                  # mov edx,[esi+4]
    code += bytes([0x89, 0x17])                        # mov [edi],edx
    code += bytes([0x8B, 0x36])                        # mov esi,[esi]
    code += bytes([0x83, 0xC7, 0x04])                  # add edi,4
    code += bytes([0x49])                              # dec ecx
    code += bytes([0x75, 0xEF])                        # jnz loop
    code += b"\x61"                                            # popad
    code += b"\xff\x25" + struct.pack("<I", slot)              # jmp [slot]
    return bytes(code)


def patch_iat(handle, address: int, value: int) -> bool:
    protect = C.c_uint32(0)
    sc.k32.VirtualProtectEx.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint32,
                                        C.POINTER(C.c_uint32)]
    sc.k32.VirtualProtectEx.restype = C.c_int
    if not sc.k32.VirtualProtectEx(handle, C.c_void_p(address), 4, 0x04, C.byref(protect)):
        return False
    sc.w(handle, address, struct.pack("<I", value))
    sc.k32.VirtualProtectEx(handle, C.c_void_p(address), 4, protect.value, C.byref(protect))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--state", default=str(ROOT / "runs" / "send_hook_state.json"))
    parser.add_argument("--output")
    args = parser.parse_args()
    state_path = Path(args.state)
    pid, handle = open_client()
    try:
        if args.install:
            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
            same_process = state.get("pid") == pid
            cave = (state.get("cave") if same_process else None) or alloc(handle, 0x200, 0x40)
            record = (state.get("record") if same_process else None) or alloc(handle, 0x400, 0x04)
            slot = (state.get("slot") if same_process else None) or alloc(handle, 0x40, 0x04)
            sc.w(handle, record, bytes(0x400))
            original = struct.unpack("<I", read(handle, SEND_IAT, 4))[0]
            sc.w(handle, int(slot), struct.pack("<I", original))
            code = build_cave(int(cave), int(record), int(slot))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            ok = patch_iat(handle, SEND_IAT, int(cave))
            readback = struct.unpack("<I", read(handle, SEND_IAT, 4))[0]
            row = {"schema": 1, "pid": pid, "cave": int(cave), "record": int(record),
                   "slot": int(slot), "original_send": hex(original),
                   "iat_readback": hex(readback), "verified": readback == int(cave),
                   "patched": ok}
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
                ret, buf, length = struct.unpack_from("<III", data, base)
                if ret == 0:
                    continue
                chain = struct.unpack_from("<IIIIII", data, base + 0x20)
                entries.append({"index": (index - count) % RING_ENTRIES,
                                "ret": hex(ret), "buf": hex(buf), "len": length,
                                "head": data[base + 0x10: base + 0x20].hex(),
                                "chain": [hex(value) for value in chain if value]})
            row = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(),
                   "pid": pid, "total": count, "entries": entries}
            text = json.dumps(row, ensure_ascii=False, indent=2)
            if args.output:
                Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if args.revert:
            patch_iat(handle, SEND_IAT, int(state["original_send"], 16))
            now = struct.unpack("<I", read(handle, SEND_IAT, 4))[0]
            print(json.dumps({"reverted": now == int(state["original_send"], 16)},
                             ensure_ascii=True))
            return 0
    finally:
        sc.k32.CloseHandle(handle)
    parser.error("choose --install, --read or --revert")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
