"""Controlled experiment: bypass only the 1649370 weapon-ID equality branch.

This does not fabricate a weapon or change the name parser. It allows the
original registration routine to continue after an ID ordering mismatch.
The patch is process-local and must not be interpreted as a protocol fix.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
from trace_weapon_registration_1649370 import k32, patch, read

TARGET = 0x59B596
EXPECTED = bytes.fromhex("0f85da000000")
REPLACEMENT = b"\x90" * len(EXPECTED)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    args = ap.parse_args()
    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    try:
        before = read(handle, TARGET, len(EXPECTED))
        if before != EXPECTED:
            raise SystemExit(f"branch bytes mismatch: {before.hex() if before else None}")
        if not patch(handle, TARGET, REPLACEMENT):
            raise SystemExit("branch patch failed")
        after = read(handle, TARGET, len(EXPECTED))
        report = {"pid": args.pid, "target": hex(TARGET), "before": before.hex(),
                  "after": after.hex() if after else None, "applied": after == REPLACEMENT}
        print(json.dumps(report))
        return 0 if report["applied"] else 1
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
