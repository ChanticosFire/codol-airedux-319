"""Point Build 1649370's native LSG host buffer at the local endpoint (runtime only).

`0x7F3890` pushes `0xE3EC988` as the host string for `0xB75370`, while the
`dwauth.ini` parser fills `0x81A7F34`.  In a stock session the LSG buffer stays
uninitialised (`00 ff 00 ff`), so the native connect targets an invalid netadr.
This tool writes an explicit host into that buffer inside the private running
copy; nothing on disk changes and the write is undone when the process exits.

It exists to test one hypothesis only: if the native LSG entry connects once
`0xE3EC988` holds `127.0.0.1`, then the missing piece is whatever normally fills
that buffer (most likely the Auth response), not the client's LSG code.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
LSG_HOST_BUFFER = 0xE3EC988
CONFIG_HOST_BUFFER = 0x81A7F34


def read(handle, address: int, size: int) -> bytes:
    import ctypes as C

    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=LSG_HOST_BUFFER)
    parser.add_argument("--output")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    try:
        before = read(handle, args.address, 32)
        payload = args.host.encode("latin-1") + b"\x00"
        sc.w(handle, args.address, payload)
        after = read(handle, args.address, 32)
        row = {
            "schema": 1,
            "build": 1649370,
            "utc": datetime.now(timezone.utc).isoformat(),
            "pid": pid,
            "address": hex(args.address),
            "host": args.host,
            "before_hex": before.hex(),
            "after_hex": after.hex(),
            "config_host": read(handle, CONFIG_HOST_BUFFER, 32).split(b"\x00")[0].decode("latin-1"),
            "runtime_only": True,
        }
    finally:
        sc.k32.CloseHandle(handle)
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(json.dumps(row, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
