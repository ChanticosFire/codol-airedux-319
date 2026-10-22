"""Read Build 1649370's native Auth/LSG configuration buffers (read-only).

`0x7F3890` builds its LSG netadr from the string buffer at `0xE3EC988` plus the
port at `0x81A9780`.  This probe dumps those runtime values together with the
three Auth source pointers so a mismatch between `dwauth.ini` and the native
connection target is visible before invoking the LSG entry.
"""
from __future__ import annotations

import argparse
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
HOST_BUFFER = 0xE3EC988
HOST_ALT = 0x81A7F34
PORT_GLOBAL = 0x81A9780


def read(handle, address: int, size: int) -> bytes:
    import ctypes as C
    from ctypes import wintypes as W

    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    sc.k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    return buf.raw[: got.value]


def describe(blob: bytes) -> dict:
    raw = blob
    text = raw.split(b"\x00")[0]
    wide = raw[: len(raw) - (len(raw) % 2)].decode("utf-16-le", "replace").split("\x00")[0]
    return {
        "hex": raw.hex(),
        "ascii": text.decode("latin-1", "replace"),
        "utf16": wide,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write JSON evidence to this path")
    args = parser.parse_args()
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x0410, False, pid)  # QUERY_INFORMATION | VM_READ
    if not handle:
        raise OSError("OpenProcess failed")
    try:
        row = {
            "schema": 1,
            "build": 1649370,
            "utc": datetime.now(timezone.utc).isoformat(),
            "pid": pid,
            "host_buffer": {"address": hex(HOST_BUFFER), **describe(read(handle, HOST_BUFFER, 96))},
            "host_alt": {"address": hex(HOST_ALT), **describe(read(handle, HOST_ALT, 96))},
            "lsg_port": struct.unpack("<H", read(handle, PORT_GLOBAL, 2))[0],
            "auth_port_global_0x81a9ec4": struct.unpack("<H", read(handle, 0x81A9EC4, 2))[0],
            "auth_sources": {
                hex(address): hex(sc.u32(handle, address))
                for address in (0x84ABB08, 0x84ABB0C, 0x84ABB14)
            },
            "account_state": sc.u32(handle, 0x84ABA60),
            "lsg_state": sc.u32(handle, 0x84ABA7C),
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
