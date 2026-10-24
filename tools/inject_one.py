"""Inject exactly one netchan message into the client's loopback receive ring.

    python tools/inject_one.py --kind challenge --cookie 1469978033
    python tools/inject_one.py --kind connect
    python tools/inject_one.py --kind gamestate --file runs/gamestate-native.bin
    python tools/inject_one.py --kind raw --hex 0000...
    python tools/inject_one.py --set-state 3

Unlike inject_client_gamestate.py this writes one message per call so the
client can be stepped through 3 -> 5 -> 6 -> 9 and each transition observed.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import socket
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

RING_BASE = 0x786DBC0
RING_READ = 0x7872C00
RING_WRITE = 0x7872C04
STATE = 0x76446B0


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
    ap.add_argument("--kind", choices=("challenge", "connect", "gamestate", "raw"), default="raw")
    ap.add_argument("--cookie", type=int, default=1469978033)
    ap.add_argument("--file", type=Path)
    ap.add_argument("--hex")
    ap.add_argument("--set-state", type=int)
    ap.add_argument("--output")
    args = ap.parse_args()

    if args.kind == "challenge":
        payload = b"\xff\xff\xff\xffchallengeResponse " + str(args.cookie).encode() + b"\0"
    elif args.kind == "connect":
        payload = (b"\xff\xff\xff\xffconnectResponse \\mapname\\mp_cross_fire\\gametype\\war"
                   b"\\sv_maxclients\\12\\protocol\\1\\shortversion\\1.1.1.13\0")
    elif args.kind == "gamestate":
        if not args.file:
            raise SystemExit("--file required for gamestate")
        payload = args.file.read_bytes()
    else:
        if not args.hex:
            raise SystemExit("--hex required for raw")
        payload = bytes.fromhex(args.hex)

    handle = k32.OpenProcess(0x0438, False, find_pid())

    def u32(address: int) -> int:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)) or got.value != 4:
            return 0
        return struct.unpack("<I", buf.raw)[0]

    adr = struct.pack("<I4sHHIII", 4, b"\x7f\x00\x00\x01", socket.htons(28969), 0, 0, 0, 0x9D)
    result = {"kind": args.kind, "length": len(payload), "state_before": u32(STATE)}
    wrote = C.c_size_t()
    for _ in range(100):
        cursor = u32(RING_WRITE)
        read = u32(RING_READ)
        if cursor - read < 14:
            slot = RING_BASE + (cursor & 0xF) * 0x504
            for address, blob in ((slot, adr), (slot + 0x18, payload),
                                  (slot + 0x500, struct.pack("<I", len(payload)))):
                k32.WriteProcessMemory(handle, C.c_void_p(address),
                                       C.create_string_buffer(blob, len(blob)), len(blob), C.byref(wrote))
            k32.WriteProcessMemory(handle, C.c_void_p(RING_WRITE),
                                   C.create_string_buffer(struct.pack("<I", cursor + 1), 4), 4, C.byref(wrote))
            result["slot"] = hex(slot)
            result["cursor_after"] = cursor + 1
            break
        time.sleep(0.1)
    else:
        raise SystemExit("ring full")
    if args.set_state is not None:
        k32.WriteProcessMemory(handle, C.c_void_p(STATE),
                               C.create_string_buffer(struct.pack("<I", args.set_state), 4), 4, C.byref(wrote))
    time.sleep(0.5)
    result["state_after"] = u32(STATE)
    text = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
