"""Invoke the 1649370 Auth state entry once in a private guarded game run.

The game must already be staged with local dwauth.ini and a per-process WFP
loopback guard. This records state before and after without patching code.
"""
from __future__ import annotations

import argparse
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import probe_conn_tcp as probe
import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]


def snapshot(handle):
    return {
        "auth_port": sc.u32(handle, 0x81A9EC4) & 0xFFFF,
        "lsg_port": sc.u32(handle, 0x81A9780) & 0xFFFF,
        "account_state": sc.u32(handle, 0x84ABA60),
        "ui_state": sc.u32(handle, 0x84ABA50),
        "lsg_state": sc.u32(handle, 0x84ABA7C),
        "auth_sources": {hex(a): hex(sc.u32(handle, a)) for a in
                         (0x84ABB08, 0x84ABB0C, 0x84ABB14)},
        "netobj": hex(sc.u32(handle, 0x8269774)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-state", type=int, choices=(0, 6), default=0)
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(), "pid": pid}
    try:
        row["before"] = snapshot(handle)
        if row["before"]["auth_port"] != 28969 or row["before"]["lsg_port"] != 28969:
            raise RuntimeError("local Auth/LSG config was not loaded")
        if row["before"]["account_state"] != args.expect_state:
            raise RuntimeError("account state is not at the expected gate")
        row["invoke"] = probe.invoke(handle, lambda cave:
            b"\xe8" + struct.pack("<i", 0x7F28F0 - (cave + 5)) + b"\xc3")
        row["immediate"] = snapshot(handle)
        time.sleep(3)
        row["after_3s"] = snapshot(handle)
    finally:
        sc.k32.CloseHandle(handle)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output = ROOT / "evidence" / "experiments" / f"{stamp}-1649370-natural-auth-start.json"
    output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(output), **row}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
