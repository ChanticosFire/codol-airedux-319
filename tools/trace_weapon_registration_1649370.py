"""Trace the original 1649370 weapon-slot parser after BG_WeaponIndexForName.

The hook sits at 0x59B591, just after 0x42F3E0 returned and before the
parser compares EAX with EDI. Each record contains the slot, returned ID,
name pointer, table count, cache index, and slot entry pointer. It records
data only; it never changes the result or branch. Use on an isolated client
after restoring 0x59B560, and restore the hook before leaving the session.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from ctypes import wintypes as W
from pathlib import Path

SITES = {
    "post_register": (0x59B591, bytes.fromhex("83c4083bc7")),  # add esp,8; cmp eax,edi
    "post_lookup": (0x42F411, bytes.fromhex("83c40485c0")),    # add esp,4; test eax,eax
    "scan_start": (0x42F351, bytes.fromhex("53bb01000000")),   # push ebx; mov ebx,1
    "scan_loop": (0x42F360, bytes.fromhex("807dff008b049d508b9801")),
}
CAPACITY = 8192
RECORD_SIZE = 28
RECORD_OFFSET = 0x1000
COUNT_OFFSET = 0x200

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.VirtualProtectEx.restype = W.BOOL
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.FlushInstructionCache.restype = W.BOOL


def read(handle, address: int, size: int) -> bytes | None:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)) or got.value != size:
        return None
    return buf.raw


def write(handle, address: int, data: bytes) -> bool:
    got = C.c_size_t()
    return bool(k32.WriteProcessMemory(handle, C.c_void_p(address), C.create_string_buffer(data),
                                      len(data), C.byref(got))) and got.value == len(data)


def patch(handle, address: int, data: bytes) -> bool:
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(address), len(data), 0x40, C.byref(old)):
        return False
    ok = write(handle, address, data)
    discard = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(address), len(data), old.value, C.byref(discard))
    k32.FlushInstructionCache(handle, C.c_void_p(address), len(data))
    return ok


def rel32(origin_after: int, destination: int) -> bytes:
    return struct.pack("<I", (destination - origin_after) & 0xFFFFFFFF)


def build_code(cave: int, target: int, original: bytes) -> bytes:
    count = cave + COUNT_OFFSET
    records = cave + RECORD_OFFSET
    code = bytearray()
    code += b"\x60"                                 # pushad
    code += b"\x8b\x0d" + struct.pack("<I", count)   # mov ecx,[count]
    code += b"\x81\xf9" + struct.pack("<I", CAPACITY) # cmp ecx,capacity
    skip_jump = len(code)
    code += b"\x0f\x83\x00\x00\x00\x00"           # jae skip
    code += b"\x8b\xd1"                             # mov edx,ecx
    code += b"\x6b\xd2\x1c"                         # imul edx,edx,28
    code += b"\x81\xc2" + struct.pack("<I", records) # add edx,records
    code += b"\x89\x3a"                             # mov [edx],edi
    code += b"\x89\x42\x04"                         # mov [edx+4],eax
    code += b"\x89\x72\x08"                         # mov [edx+8],esi
    code += b"\x8b\x1d" + struct.pack("<I", 0x827F738) # mov ebx,[weapon_table_count]
    code += b"\x89\x5a\x0c"                         # mov [edx+12],ebx
    code += b"\x8b\x1d" + struct.pack("<I", 0x827F73C) # mov ebx,[cached_weapon_index]
    code += b"\x89\x5a\x10"                         # mov [edx+16],ebx
    code += b"\x8b\x1c\xbd" + struct.pack("<I", 0x1988B50) # mov ebx,[edi*4+table]
    code += b"\x89\x5a\x14"                         # mov [edx+20],ebx
    code += b"\x85\xdb\x74\x02\x8b\x1b"           # if entry: ebx=[entry]
    code += b"\x89\x5a\x18"                         # mov [edx+24],ebx
    code += b"\xff\x05" + struct.pack("<I", count)   # inc dword [count]
    skip = len(code)
    code[skip_jump + 2:skip_jump + 6] = rel32(cave + skip_jump + 6, cave + skip)
    code += b"\x61"                                 # popad
    code += original                                  # replay stolen instructions
    code += b"\xe9" + rel32(cave + len(code) + 5, target + len(original))
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--meta", type=Path, required=True)
    ap.add_argument("--site", choices=tuple(SITES), default="post_register")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--read", action="store_true")
    mode.add_argument("--restore", action="store_true")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    target, original = SITES[args.site]
    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    try:
        if args.install:
            before = read(handle, target, len(original))
            if before != original:
                raise SystemExit(f"target bytes mismatch: {before.hex() if before else None}")
            cave = int(k32.VirtualAllocEx(handle, None, 0x40000, 0x3000, 0x40) or 0)
            if not cave:
                raise SystemExit("VirtualAllocEx failed")
            code = build_code(cave, target, original)
            if not write(handle, cave, code) or not write(handle, cave + COUNT_OFFSET, b"\0" * 4):
                raise SystemExit("write trace cave failed")
            jump = b"\xe9" + rel32(target + 5, cave)
            if not patch(handle, target, jump):
                raise SystemExit("write target jump failed")
            report = {"pid": args.pid, "site": args.site, "target": hex(target), "cave": hex(cave),
                      "capacity": CAPACITY, "original": original.hex(),
                      "target_after": (read(handle, target, 5) or b"").hex()}
            args.meta.parent.mkdir(parents=True, exist_ok=True)
            args.meta.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
            return 0
        meta = json.loads(args.meta.read_text(encoding="utf-8"))
        if meta["pid"] != args.pid or meta["target"] != hex(target):
            raise SystemExit("metadata does not match target process")
        cave = int(meta["cave"], 16)
        if args.restore:
            if not patch(handle, target, original):
                raise SystemExit("restore write failed")
            print(json.dumps({"pid": args.pid, "site": args.site,
                              "restored": read(handle, target, len(original)) == original}))
            return 0
        raw_count = read(handle, cave + COUNT_OFFSET, 4)
        if not raw_count:
            raise SystemExit("trace count unreadable")
        count = min(struct.unpack("<I", raw_count)[0], CAPACITY)
        data = read(handle, cave + RECORD_OFFSET, count * RECORD_SIZE) if count else b""
        if data is None:
            raise SystemExit("trace records unreadable")
        rows = []
        for offset in range(0, len(data), RECORD_SIZE):
            slot, returned, pointer, table_count, cached_index, entry_ptr, entry_name_ptr = struct.unpack_from("<IIIIIII", data, offset)
            name_bytes = read(handle, pointer, 96) if pointer else None
            name = name_bytes.split(b"\0", 1)[0].decode("latin-1", "replace") if name_bytes else None
            entry_name_bytes = read(handle, entry_name_ptr, 96) if entry_name_ptr else None
            entry_name = (entry_name_bytes.split(b"\0", 1)[0].decode("latin-1", "replace")
                          if entry_name_bytes else None)
            rows.append({"slot": slot, "returned": returned, "name": name,
                         "table_count_after": table_count, "cached_index": cached_index,
                         "expected_slot_entry": hex(entry_ptr),
                         "expected_slot_entry_name_ptr": hex(entry_name_ptr),
                         "expected_slot_entry_name": entry_name})
        mismatch = next((i for i, row in enumerate(rows) if row["slot"] != row["returned"]), None)
        report = {"pid": args.pid, "site": args.site, "count": count, "first_mismatch_record": mismatch,
                  "around_first_mismatch": rows[max(0, mismatch - 4):mismatch + 5] if mismatch is not None else [],
                  "rows": rows}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
        return 0
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
