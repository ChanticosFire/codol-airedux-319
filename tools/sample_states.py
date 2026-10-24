"""Sample key connection/load fields whenever net_state changes.

    python tools/sample_states.py --seconds 45

Fields tracked:
    net_state  = [0x76446B0]
    ui_state   = [0x84ABA50]
    load_status= [0x84ABA7C]
    table      = [0x827F738]   (weapon definitions)
    conn_5E8   = [conn + 0x5E8] where conn = [0x331C0C8] ^ 0xD362501F
    conn_640   = [conn + 0x640]

One line is printed per (net_state, ui_state, load_status) change so the Gantt of
the whole connect+gamestate sequence stays readable.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

NET_STATE, UI_STATE, LOAD_STATUS, TABLE = 0x76446B0, 0x84ABA50, 0x84ABA7C, 0x827F738
CONN_ENC, CONN_XOR = 0x331C0C8, 0xD362501F


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--interval", type=float, default=0.1)
    ap.add_argument("--output")
    args = ap.parse_args()
    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int | None:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return None
        return struct.unpack("<I", buf.raw)[0]

    rows, last = [], None
    start = time.time()
    while time.time() - start < args.seconds:
        net, ui, load, table = u32(NET_STATE), u32(UI_STATE), u32(LOAD_STATUS), u32(TABLE)
        raw = u32(CONN_ENC)
        conn = (raw ^ CONN_XOR) if raw else 0
        c5e8 = u32(conn + 0x5E8) if conn else None
        c640 = u32(conn + 0x640) if conn else None
        key = (net, ui, load, table)
        if key != last:
            last = key
            row = {"t": round(time.time() - start, 2), "net": net, "ui": ui,
                   "load": load, "table": table, "conn_5E8": c5e8, "conn_640": c640}
            rows.append(row)
            print(json.dumps(row), flush=True)
        time.sleep(args.interval)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
