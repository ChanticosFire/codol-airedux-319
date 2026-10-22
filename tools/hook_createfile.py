"""Ring-record the file names opened by the 1649370 client.

Replaces the CreateFileW IAT slot (0xCA8284) with a cave that records the return
address and the lpFileName pointer into a ring buffer, so the names the client
tries to open right before a crash become visible.

    python tools/hook_createfile.py --install
    python tools/hook_createfile.py --read
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
STATE = ROOT / "runs" / "createfile_hook_state.json"
CREATE_IAT = 0xCA8284
RING_ENTRIES = 16
ENTRY_SIZE = 0x10


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
    code += b"\x83\xe0\x0f"                                    # and eax,15
    code += b"\xc1\xe0\x04"                                    # shl eax,4
    code += b"\x05" + struct.pack("<I", entries)               # add eax,entries
    code += b"\x8b\x4c\x24\x20"                                # mov ecx,[esp+0x20] (return addr)
    code += b"\x89\x08"                                        # mov [eax],ecx
    code += b"\x8b\x4c\x24\x24"                                # mov ecx,[esp+0x24] (lpFileName)
    code += b"\x89\x48\x04"                                    # mov [eax+4],ecx
    code += b"\x8b\x4c\x24\x28"                                # mov ecx,[esp+0x28] (dwDesiredAccess)
    code += b"\x89\x48\x08"                                    # mov [eax+8],ecx
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
    parser.add_argument("--output")
    args = parser.parse_args()
    pid, handle = open_client()
    row = {"schema": 1, "build": 1649370, "pid": pid,
           "utc": datetime.now(timezone.utc).isoformat()}
    try:
        if args.install:
            state = json.loads(STATE.read_text()) if STATE.is_file() else {}
            same = state.get("pid") == pid
            cave = (state.get("cave") if same else None) or alloc(handle, 0x200, 0x40)
            record = (state.get("record") if same else None) or alloc(handle, 0x400, 0x04)
            slot = (state.get("slot") if same else None) or alloc(handle, 0x40, 0x04)
            sc.w(handle, record, bytes(0x400))
            original = struct.unpack("<I", read(handle, CREATE_IAT, 4))[0]
            sc.w(handle, int(slot), struct.pack("<I", original))
            code = build_cave(int(cave), int(record), int(slot))
            sc.w(handle, int(cave), code)
            sc.k32.FlushInstructionCache(handle, C.c_void_p(int(cave)), len(code))
            ok = patch_iat(handle, CREATE_IAT, int(cave))
            readback = struct.unpack("<I", read(handle, CREATE_IAT, 4))[0]
            row.update(cave=int(cave), record=int(record), slot=int(slot),
                       original=hex(original), iat_readback=hex(readback),
                       verified=readback == int(cave), patched=ok,
                       status="installed" if ok else "patch_failed")
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(row, indent=2) + "\n")
        elif args.read:
            state = json.loads(STATE.read_text())
            record = int(state["record"])
            data = read(handle, record, 0x10 + RING_ENTRIES * ENTRY_SIZE)
            count = struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else 0
            entries = []
            for index in range(RING_ENTRIES):
                base = 0x10 + index * ENTRY_SIZE
                if base + ENTRY_SIZE > len(data):
                    break
                ret, name_ptr, access = struct.unpack_from("<III", data, base)
                if not name_ptr:
                    continue
                raw = read(handle, name_ptr, 260)
                name = raw.split(b"\x00\x00")[0]
                try:
                    text = name.decode("utf-16-le", "ignore")
                except Exception:
                    text = ""
                entries.append({"ret": hex(ret), "access": hex(access), "name": text})
            row.update(count=count, entries=entries, status="read")
        else:
            row["status"] = "no_action"
    finally:
        sc.k32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
