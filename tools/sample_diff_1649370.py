"""Multi-sample diff that labels every sample with the live weapon value.

Cycles the snapshot sequence so the weapon state changes between samples; each
sample records ps.weapon plus a 2 MB dump, then reports which byte ranges differ
between consecutive samples and which sample pair crossed a weapon change.

    python tools/sample_diff_1649370.py --pid 123 --samples 5 --gap 0.2
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import time
from ctypes import wintypes as W
from pathlib import Path

BASE = 0x1C00000
SIZE = 0x200000
CL_ENCODED = 0x76638F4
CL_XOR = 0x6891D1C7
PS_OFFSET = 0x0C
PS_WEAPON = 0x4C


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--gap", type=float, default=0.2)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit("OpenProcess failed")

    def u32(address: int) -> int | None:
        buf = ctypes.create_string_buffer(4)
        got = ctypes.c_size_t()
        if k32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, 4, ctypes.byref(got)):
            return struct.unpack("<I", buf.raw)[0]
        return None

    def weapon() -> int | None:
        encoded = u32(CL_ENCODED)
        if not encoded:
            return None
        cl = (encoded ^ CL_XOR) & 0xFFFFFFFF
        return u32(cl + PS_OFFSET + PS_WEAPON)

    samples = []
    for index in range(args.samples):
        value = weapon()
        buf = ctypes.create_string_buffer(SIZE)
        got = ctypes.c_size_t()
        k32.ReadProcessMemory(handle, ctypes.c_void_p(BASE), buf, SIZE, ctypes.byref(got))
        samples.append({"index": index, "weapon": value, "data": buf.raw[:got.value]})
        time.sleep(args.gap)

    pairs = []
    for index in range(len(samples) - 1):
        first, second = samples[index], samples[index + 1]
        diffs = [i for i in range(min(len(first["data"]), len(second["data"])))
                 if first["data"][i] != second["data"][i]]
        ranges = []
        for offset in diffs:
            if ranges and offset - ranges[-1][1] <= 8:
                ranges[-1][1] = offset
            else:
                ranges.append([offset, offset])
        pairs.append({
            "from": {"weapon": first["weapon"]},
            "to": {"weapon": second["weapon"]},
            "weapon_changed": first["weapon"] != second["weapon"],
            "diff_bytes": len(diffs),
            "ranges": [{"addr": hex(BASE + start), "len": end - start + 1,
                        "a": first["data"][start:end + 1].hex()[:40],
                        "b": second["data"][start:end + 1].hex()[:40]}
                       for start, end in ranges if end - start + 1 <= 16][:40],
        })
    report = {"pid": args.pid, "samples": [{"index": s["index"], "weapon": s["weapon"]}
                                           for s in samples], "pairs": pairs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"weapons": [s["weapon"] for s in samples],
                      "pairs": [{"w": p["weapon_changed"], "n": p["diff_bytes"]} for p in pairs]},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
