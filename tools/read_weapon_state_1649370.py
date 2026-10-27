"""Read the live 1649370 weapon table, model cache and playerState tail (read-only).

Established addresses (see `tools/read_client_ps_1649370.py` for provenance):

    cl            = *(0x76638F4) ^ 0x6891D1C7
    ps            = cl + 0x0C
    weapon defs   = 0x1988B50[weapon]   (pointer table, zero when unregistered)
    model cache   = 0x1C166E8 + weapon*16  {key, registered, modelA, modelB}

Tail section targets inside the playerState structure come from the 1649370
retained-engine overlay (`codol_player_tail164.h`):

    inventory[15][7] at PS756/816      clip[15][3] at PS1172
    reserve[15][2]   at PS1052

This tool never writes to the client.

    python tools/read_weapon_state_1649370.py --pid 1234 --ids 78 --ps-words
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
from ctypes import wintypes as W

CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
NET_STATE = 0x76446B0
PS_BASE = 0x0C
WEAPON_TABLE = 0x1988B50
MODEL_CACHE = 0x1C166E8
CACHE_STRIDE = 16

TAIL_OFFSETS = {
    "inventory": 756,
    "inventory_b": 816,
    "reserve": 1052,
    "clip": 1172,
}

WEAPON_FIELDS = (0x00, 0x04, 0x08, 0x0C, 0x10, 0x28, 0x58C, 0x80, 0x178,
                 0x7B4, 0x7BC, 0x7C0, 0x7C4)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--ids", default="78", help="comma separated weapon IDs")
    ap.add_argument("--ps-words", action="store_true",
                    help="also dump the non-zero dwords around the tail targets")
    ap.add_argument("--scan-weapons", type=int, default=0,
                    help="scan this many weapon-table entries and report non-zero ones")
    args = ap.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for pid {args.pid}")

    def read(addr: int, size: int):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size,
                                     ctypes.byref(got)):
            return None
        return buf.raw if got.value == size else None

    def u32(addr: int):
        raw = read(addr, 4)
        return None if raw is None else struct.unpack("<I", raw)[0]

    def cstr(addr: int, limit: int = 96):
        raw = read(addr, limit)
        if raw is None:
            return None
        return raw.split(b"\x00")[0].decode("latin-1", "replace")

    out: dict = {"pid": args.pid, "net_state": u32(NET_STATE)}
    encoded = u32(CL_PTR)
    if not encoded:
        raise SystemExit("cl pointer is null")
    cl = encoded ^ CL_XOR
    ps = cl + PS_BASE
    out["cl"] = hex(cl)
    out["ps"] = hex(ps)

    ids = [int(part) for part in args.ids.split(",") if part.strip()]
    weapons = {}
    for weapon in ids:
        entry = {"id": weapon}
        pointer = u32(WEAPON_TABLE + weapon * 4)
        entry["def_ptr"] = None if pointer is None else hex(pointer)
        if pointer:
            blob = read(pointer, 0x800)
            if blob:
                fields = {}
                for offset in WEAPON_FIELDS:
                    if offset + 4 <= len(blob):
                        fields[hex(offset)] = struct.unpack_from("<I", blob, offset)[0]
                entry["def_fields"] = fields
                for offset, label in ((0x0, "name"), (0x4, "display"),
                                      (0x80, "field80_str"), (0x178, "field178_str")):
                    inner = struct.unpack_from("<I", blob, offset)[0]
                    entry[label] = cstr(inner) if inner else None
        cache_addr = MODEL_CACHE + weapon * CACHE_STRIDE
        cache = read(cache_addr, CACHE_STRIDE)
        entry["cache"] = None if cache is None else list(struct.unpack("<4I", cache))
        entry["cache_addr"] = hex(cache_addr)
        weapons[weapon] = entry
    out["weapons"] = weapons

    registered = []
    for weapon in range(1200):
        if u32(WEAPON_TABLE + weapon * 4):
            registered.append(weapon)
    out["registered_count"] = len(registered)
    out["registered_tail"] = registered[-12:]

    cache_nonzero = 0
    nonzero_entries = []
    for weapon in range(1200):
        cache = read(MODEL_CACHE + weapon * CACHE_STRIDE, CACHE_STRIDE)
        if not cache:
            continue
        words = struct.unpack("<4I", cache)
        if any(words):
            cache_nonzero += 1
            if len(nonzero_entries) < 20:
                nonzero_entries.append([weapon, list(words)])
    out["cache_nonzero_count"] = cache_nonzero
    out["cache_nonzero_sample"] = nonzero_entries

    if args.scan_weapons:
        out["scan"] = []
        for weapon in range(args.scan_weapons):
            pointer = u32(WEAPON_TABLE + weapon * 4)
            if pointer:
                name = cstr(pointer)
                out["scan"].append([weapon, hex(pointer), name])

    if args.ps_words:
        origins = {}
        for name, offset in TAIL_OFFSETS.items():
            blob = read(ps + offset, 96)
            origins[name] = None if blob is None else list(struct.unpack("<24I", blob))
        out["tail"] = origins
        blob = read(ps, 0x3C00)
        nonzero = []
        if blob:
            for offset in range(0, len(blob) - 3, 4):
                word = struct.unpack_from("<I", blob, offset)[0]
                if word:
                    nonzero.append([hex(offset), word])
        out["ps_nonzero"] = nonzero

    print(json.dumps(out, indent=2))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
