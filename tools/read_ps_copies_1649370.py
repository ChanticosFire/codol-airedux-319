"""Read every live playerState copy of a 1649370 client found by a marker hit.

The client keeps several copies of the playerState: the network one at cl+0x0C,
a ring of snapshot copies, and cgame's own predicted/snapshot copies.  Writing a
marker word through the snapshot wire makes every copy findable, so this tool
takes marker hit addresses, subtracts the marker offset (0x174) and prints the
fields that decide whether the first-person weapon is drawn.

    python tools/read_ps_copies_1649370.py --pid 1234 --hits 0x130809e8,0x1308b3ec
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
from ctypes import wintypes as W

MARKER_OFFSET = 0x174
FIELDS = (
    ("weapon", 0x04C, "u32"),
    ("weaponstate_guess", 0x050, "i16"),
    ("viewmodelIndex", 0x15C, "u32"),
    ("viewHeightTarget", 0x16C, "i32"),
    ("viewHeightCurrent", 0x170, "f32"),
    ("groundEntityNum", 0x0C0, "u32"),
    ("primary", 0x3F8, "u32"),
    ("altWeapon", 0x3FC, "u32"),
    ("clipWeapon", 0x494, "u32"),
    ("clipCount", 0x498, "u32"),
    ("inventory0", 0x2F4, "u32"),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--hits", required=True, help="comma separated VA hits of the marker")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
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

    rows = []
    for text in args.hits.split(","):
        text = text.strip()
        if not text:
            continue
        hit = int(text, 0)
        base = (hit - MARKER_OFFSET) & 0xFFFFFFFF
        entry = {"marker": hex(hit), "ps": hex(base)}
        for name, offset, kind in FIELDS:
            raw = read(base + offset, 4)
            if raw is None:
                entry[name] = None
                continue
            if kind == "f32":
                entry[name] = round(struct.unpack("<f", raw)[0], 4)
            elif kind == "i32":
                entry[name] = struct.unpack("<i", raw)[0]
            elif kind == "i16":
                entry[name] = struct.unpack("<h", raw[:2])[0]
            else:
                entry[name] = struct.unpack("<I", raw)[0]
        rows.append(entry)

    report = {"pid": args.pid, "copies": rows}
    text = json.dumps(report, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle_out:
            handle_out.write(text)
    print(text)
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
