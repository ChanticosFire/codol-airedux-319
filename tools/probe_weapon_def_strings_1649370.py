"""Dump a live client's weapon definition strings and show which pointer fields
reference a given model name.

    python tools/probe_weapon_def_strings_1649370.py --pid 1234 --def 0x2a392d4 --find 0x4c7f77ec
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
from ctypes import wintypes as W


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--weapon-def", type=lambda text: int(text, 0), required=True)
    ap.add_argument("--size", type=lambda text: int(text, 0), default=0x800)
    ap.add_argument("--find", type=lambda text: int(text, 0), default=None)
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
        return buf.raw[:got.value]

    def cstr(addr: int, limit: int = 80):
        raw = read(addr, limit)
        if raw is None:
            return None
        text = raw.split(b"\x00")[0]
        try:
            return text.decode("ascii")
        except UnicodeDecodeError:
            return None

    blob = read(args.weapon_def, args.size)
    if blob is None:
        raise SystemExit("weapon def unreadable")
    hits = []
    if args.find is not None:
        needle = struct.pack("<I", args.find)
        start = 0
        while True:
            index = blob.find(needle, start)
            if index < 0:
                break
            if index % 4 == 0:
                hits.append(hex(index))
            start = index + 1
    strings = {}
    for offset in range(0, len(blob) - 3, 4):
        word = struct.unpack_from("<I", blob, offset)[0]
        if 0x0400000 <= word < 0x7F000000 and not (0x2000000 <= word < 0x4000000):
            text = cstr(word)
            if text and len(text) >= 3 and all(32 <= ord(ch) < 127 for ch in text):
                strings[hex(offset)] = text
    report = {"def": hex(args.weapon_def), "size": len(blob),
              "find": None if args.find is None else hex(args.find),
              "find_offsets": hits, "strings": strings}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


