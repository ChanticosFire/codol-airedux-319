"""Invoke Build 1649370's existing 0x7F3800 LSG state entry once.

Run only against a private guarded game session with local dwauth.ini staged.
Does not patch game code or the community sources.
"""
from __future__ import annotations

import argparse
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import probe_conn_tcp as probe
import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-state", type=int, choices=(0, 1, 2), default=0)
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(), "pid": pid}
    try:
        row["before"] = {"global_state": sc.u32(handle, 0x84ABA7C),
                         "port": sc.u32(handle, 0x81A9780) & 0xFFFF,
                         "netobj": hex(sc.u32(handle, 0x8269774))}
        if row["before"]["port"] != 28969:
            raise RuntimeError("local LSG config was not loaded")
        if row["before"]["global_state"] != args.expect_state:
            raise RuntimeError("LSG state is not at the expected gate")
        row["invoke"] = probe.invoke(handle, lambda cave:
            b"\xe8" + struct.pack("<i", 0x7F3800 - (cave + 5)) + b"\xc3")
        netobj = sc.u32(handle, 0x8269774)
        conn = sc.u32(handle, netobj + 0x4F4) if netobj else 0
        row["after"] = {"global_state": sc.u32(handle, 0x84ABA7C),
                        "netobj": hex(netobj), "conn": hex(conn),
                        "conn_c8": sc.u32(handle, conn + 0xC8) if conn else None,
                        "auth_source_present": any(sc.u32(handle, a) != 0 for a in
                                                   (0x84ABB08, 0x84ABB0C, 0x84ABB14))}
    finally:
        sc.k32.CloseHandle(handle)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = ROOT / "evidence" / "experiments" / f"{stamp}-1649370-natural-lsg-start.json"
    output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(output), **row}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
