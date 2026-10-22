"""Write a small, verified byte patch into the running 1649370 client.

The staged private runtime is disposable, so runtime patches are the normal way
to test a hypothesis without touching any on-disk artifact.  This tool reads the
original bytes, writes the replacement, re-reads them, and records everything
(including how to revert) in JSON evidence.

First use: bypass the bdService message HMAC comparison at 0xBA39D4
(`je 0xBA39E7`, bytes 74 11) with `jmp 0xBA39E7` (EB 11), to prove that the HMAC
check is the only reason lobby replies were dropped.

    python tools/patch_client_bytes.py --at 0xba39d4 --bytes eb11 --verify
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", required=True, type=lambda value: int(value, 0))
    parser.add_argument("--bytes", required=True, help="hex replacement bytes")
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = bytes.fromhex(args.bytes)
    pid = sc.find_pid()
    handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError("OpenProcess failed")
    try:
        import ctypes as C
        before = C.create_string_buffer(len(payload))
        got = C.c_size_t()
        sc.k32.ReadProcessMemory(handle, C.c_void_p(args.at), before, len(payload), C.byref(got))
        original = before.raw[: got.value]
        written = sc.w(handle, args.at, payload)
        sc.k32.FlushInstructionCache.argtypes = [__import__("ctypes").wintypes.HANDLE, __import__("ctypes").c_void_p, __import__("ctypes").c_size_t]
        sc.k32.FlushInstructionCache(handle, __import__("ctypes").c_void_p(args.at), len(payload))
        after = C.create_string_buffer(len(payload))
        sc.k32.ReadProcessMemory(handle, C.c_void_p(args.at), after, len(payload), C.byref(got))
        row = {
            "schema": 1, "build": 1649370,
            "utc": datetime.now(timezone.utc).isoformat(), "pid": pid,
            "address": hex(args.at),
            "original_hex": original.hex(),
            "patched_hex": payload.hex(),
            "readback_hex": after.raw[: got.value].hex(),
            "verified": after.raw[: got.value] == payload,
            "runtime_only": True,
            "revert_hex": original.hex(),
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
