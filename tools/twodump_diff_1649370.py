"""Two dumps inside one session, then diff (cancels heap/timestamp noise).

Run through session_retry --after-success with a snapshot sequence that cycles
the weapon state (r684-seq: 78 -> 0 -> 78), so the two dumps land on different
frames of the same process.

    python tools/twodump_diff_1649370.py --pid 123 --out runs/r726.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import time
from ctypes import wintypes as W
from pathlib import Path

BASE = 0x1C00000
SIZE = 0x200000  # 2 MB: engine/globals band, small enough for a fast double dump


def snapshot(handle, k32) -> bytes:
    buf = ctypes.create_string_buffer(SIZE)
    got = ctypes.c_size_t()
    k32.ReadProcessMemory(handle, ctypes.c_void_p(BASE), buf, SIZE, ctypes.byref(got))
    return buf.raw[:got.value]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--gap", type=float, default=0.5)
    args = ap.parse_args()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    handle = k32.OpenProcess(0x438, False, args.pid)
    if not handle:
        raise SystemExit("OpenProcess failed")
    first = snapshot(handle, k32)
    time.sleep(args.gap)
    second = snapshot(handle, k32)
    diffs = [i for i in range(min(len(first), len(second))) if first[i] != second[i]]
    ranges = []
    for index in diffs:
        if ranges and index - ranges[-1][1] <= 8:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    report = {
        "pid": args.pid, "base": hex(BASE), "size": SIZE,
        "bytes": [len(first), len(second)],
        "diff_bytes": len(diffs), "diff_ranges": len(ranges),
        "small": [{"addr": hex(BASE + start), "len": end - start + 1,
                   "a": first[start:end + 1].hex()[:32],
                   "b": second[start:end + 1].hex()[:32]}
                  for start, end in ranges if end - start + 1 <= 8][:40],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("diff_bytes", "diff_ranges")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
