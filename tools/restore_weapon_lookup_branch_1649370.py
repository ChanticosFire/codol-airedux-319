"""Restore the original 0x42F32C conditional lookup branch in one client.

The r336 compatibility patch turns JAE into an unconditional JMP. This tool
allows an isolated A/B probe while keeping the other transport patches.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json

from trace_weapon_registration_1649370 import k32, patch, read

TARGET = 0x42F32C
PATCHED = bytes.fromhex("eb23")
ORIGINAL = bytes.fromhex("7323")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    args = ap.parse_args()
    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    try:
        before = read(handle, TARGET, 2)
        if before != PATCHED:
            raise SystemExit(f"lookup branch mismatch: {before.hex() if before else None}")
        if not patch(handle, TARGET, ORIGINAL):
            raise SystemExit("lookup branch restore failed")
        after = read(handle, TARGET, 2)
        report = {"pid": args.pid, "target": hex(TARGET), "before": before.hex(),
                  "after": after.hex() if after else None, "restored": after == ORIGINAL}
        print(json.dumps(report))
        return 0 if report["restored"] else 1
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
