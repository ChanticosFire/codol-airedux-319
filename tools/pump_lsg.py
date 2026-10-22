"""Keep Build 1649370's LSG receive pump running.

The client only drives its LSG receive path while its login state machine is
active (`0x7F3800` state 1 calls `0xB838A0`).  Once the lobby is up the pump
stops, so server replies sit unread in the socket and all business responses are
effectively lost.  Calling `0xB838A0(netobj)` on a short interval drains them.

    python tools/pump_lsg.py --seconds 300 --interval 0.1
    python tools/pump_lsg.py --once
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc
import probe_conn_tcp as probe

ROOT = Path(__file__).resolve().parents[1]
NETOBJ = 0x8269774
PUMP = 0xB838A0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    calls = 0
    errors = 0
    started = time.monotonic()
    row = {"schema": 1, "build": 1649370,
           "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
           "pump": hex(PUMP), "interval": args.interval, "once": args.once}
    try:
        deadline = started if args.once else started + args.seconds
        while time.monotonic() < deadline:
            netobj = sc.u32(handle, NETOBJ)
            if not netobj:
                errors += 1
            else:
                cave = int(sc.k32.VirtualAllocEx(handle, None, 0x40, 0x3000, 0x40))
                sc.w(handle, cave,
                     b"\xb9" + struct.pack("<I", netobj)
                     + b"\xe8" + struct.pack("<i", PUMP - (cave + 10))
                     + b"\xc3")
                # The remote thread must run the whole cave; use probe.invoke's
                # thread helper but keep allocation predictable.
                tid = C.c_uint32(0)
                thread = sc.k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave),
                                                   None, 0, C.byref(tid))
                if thread:
                    sc.k32.WaitForSingleObject(thread, 200)
                    sc.k32.CloseHandle(thread)
                    calls += 1
                else:
                    errors += 1
                sc.k32.VirtualFreeEx(handle, C.c_void_p(cave), 0, 0x8000)
            if args.once:
                break
            time.sleep(max(0.01, args.interval))
    finally:
        sc.k32.CloseHandle(handle)
    row.update({"calls": calls, "errors": errors,
                "elapsed_s": round(time.monotonic() - started, 3)})
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(json.dumps(row, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
