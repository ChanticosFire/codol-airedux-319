"""Drive Build 1649370's native DW login/LSG state machine one tick at a time.

Static work on the community offline build shows one dispatcher entry:

    0x7F26C0  switch ([0x84ABA50] - 1) { 0: 0x7F3600, 1: 0x7F28F0,
                                          2: 0x7F3800, 3: 0x7F27B0 }

`0x7F3600` prepares the Auth/LSG session objects from the staged `dwauth.ini`
hosts and copies the resolved LSG netadr into `0xE3EC988`; `0x7F28F0` runs the
Auth account state machine; `0x7F3800` drives the native LSG connection.

`0x7F2600` is the smaller "begin login" entry: it advances
`[0x84ABA50]` from 0 to 1 when its guard globals allow it.

This tool calls `0x7F2600` once (optional) and then `0x7F26C0` in a bounded
loop, recording the observable gate values after each tick.  It never writes
game code in the staged copy; only the loop counters and probe cave are
allocated.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import probe_conn_tcp as probe
import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]

UI_STATE = 0x84ABA50
AUTH_STATE = 0x84ABA60
LSG_STATE = 0x84ABA7C
LOGIN_READY = 0x84ABA78
LOGIN_STEP = 0x84ABA48
AUTH_0 = 0x84ABB08
AUTH_1 = 0x84ABB0C
AUTH_2 = 0x84ABB14
NETOBJ = 0x8269774
LSG_HOST = 0xE3EC988
LSG_PORT = 0x81A9780
BEGIN_LOGIN = 0x7F2600
DISPATCH = 0x7F26C0


def read(handle, address: int, size: int) -> bytes:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def snapshot(handle) -> dict:
    netobj = sc.u32(handle, NETOBJ)
    conn = sc.u32(handle, netobj + 0x4F4) if netobj else 0
    host = read(handle, LSG_HOST, 16)
    return {
        "ui_state": sc.u32(handle, UI_STATE),
        "login_step": sc.u32(handle, LOGIN_STEP),
        "login_ready": sc.u32(handle, LOGIN_READY),
        "auth_state": sc.u32(handle, AUTH_STATE),
        "lsg_state": sc.u32(handle, LSG_STATE),
        "auth_sources": {
            hex(a): hex(sc.u32(handle, a)) for a in (AUTH_0, AUTH_1, AUTH_2)
        },
        "netobj": hex(netobj),
        "conn": hex(conn) if conn else "0x0",
        "conn_c8": sc.u32(handle, conn + 0xC8) if conn else None,
        "conn_5e8": sc.u32(handle, conn + 0x5E8) if conn else None,
        "conn_640": sc.u32(handle, conn + 0x640) if conn else None,
        "lsg_host_first16": host.hex(),
        "lsg_host_ascii": host.split(b"\x00")[0].decode("latin-1", "replace"),
        "lsg_port": struct.unpack("<H", read(handle, LSG_PORT, 2))[0],
    }


def call(handle, address: int) -> dict:
    return probe.invoke(handle, lambda cave: b"\xe8" + struct.pack("<i", address - (cave + 5)) + b"\xc3")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=40)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--start", action="store_true", help="call 0x7F2600 before ticking")
    parser.add_argument("--set-ui-state", type=int, default=None,
                        help="write [0x84ABA50] before ticking to emulate the UI start")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    rows = []
    row = {
        "schema": 1,
        "build": 1649370,
        "utc": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
        "start_entry": hex(BEGIN_LOGIN) if args.start else None,
        "dispatch_entry": hex(DISPATCH),
        "forced_ui_state": args.set_ui_state,
        "ticks": args.ticks,
        "interval": args.interval,
        "samples": rows,
    }
    try:
        row["before"] = snapshot(handle)
        if args.set_ui_state is not None:
            sc.w(handle, UI_STATE, struct.pack("<I", args.set_ui_state))
            row["after_force"] = snapshot(handle)
        if args.start:
            row["start"] = call(handle, BEGIN_LOGIN)
            time.sleep(0.5)
            row["after_start"] = snapshot(handle)
        for index in range(args.ticks):
            result = call(handle, DISPATCH)
            time.sleep(args.interval)
            sample = {"tick": index, "call": result, **snapshot(handle)}
            rows.append(sample)
            if sample["ui_state"] == 0 and index > 2:
                break
    finally:
        sc.k32.CloseHandle(handle)
    row["utc_end"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tail = rows[-1] if rows else None
    print(json.dumps({"evidence": str(output), "before": row["before"],
                      "after_start": row.get("after_start"), "last": tail},
                     ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
