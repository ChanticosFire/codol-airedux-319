"""Restore selected per-weapon table indexing masked by the r336 patch.

This is a one-process A/B probe. It checks patched bytes exactly before write.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json

from trace_weapon_registration_1649370 import k32, patch, read

SITES = {
    "init": (0x58F3B9, bytes.fromhex("8b0d508b980190"),
             bytes.fromhex("8b0c8d508b9801")),
    "other": (0x58EF76, bytes.fromhex("8b35508b980190"),
              bytes.fromhex("8b348d508b9801")),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--site", choices=tuple(SITES), default="init")
    args = ap.parse_args()
    target, patched, original = SITES[args.site]
    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    try:
        before = read(handle, target, len(patched))
        if before != patched:
            raise SystemExit(f"{args.site} bytes mismatch: {before.hex() if before else None}")
        if not patch(handle, target, original):
            raise SystemExit(f"{args.site} restore failed")
        after = read(handle, target, len(original))
        report = {"pid": args.pid, "site": args.site, "target": hex(target),
                  "before": before.hex(), "after": after.hex() if after else None,
                  "restored": after == original}
        print(json.dumps(report))
        return 0 if report["restored"] else 1
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
