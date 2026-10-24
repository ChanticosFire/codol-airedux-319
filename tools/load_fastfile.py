"""Ask the client to load one fastfile by calling Com_LoadFastfiles (0x49E160).

    python tools/load_fastfile.py common_gametype_mp

Argument layout verified from 0x49E160:
    [ebp+8]  = list pointer  (list+8 is the first entry, entries are 0xC bytes)
    [ebp+0xC]= entry count
    [ebp+0x10]= mode (0 normal, 2 special)

Each entry starts with a char* name.  This allocates a small block inside the
client, fills one entry, and calls the function on the main thread, which is the
missing step that gives the server path the 88 gametype weapons.
"""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import sys
from ctypes import wintypes as W
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ring_bridge_1649370 import Client  # noqa: E402

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

LOAD_FASTFILES = 0x49E160
ENTRY_SIZE = 0xC


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "common_gametype_mp"
    client = Client()
    base = k32.VirtualAllocEx(client.handle, None, 0x1000, 0x3000, 0x04)
    if not base:
        raise SystemExit("VirtualAllocEx failed")
    base = int(base)
    name_addr = base + 0x100
    list_addr = base + 0x200

    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(client.handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    ok = write(name_addr, name.encode() + b"\0")
    # layout: [0]=0,[4]=0 (header), [8]=name*, [0xC]=0 flags, [0x10]=0 pad
    ok = ok and write(list_addr, struct.pack("<II I I I", 0, 0, name_addr, 0, 0))
    if not ok:
        raise SystemExit("write failed")
    row = client.invoke_sequence([{"target": LOAD_FASTFILES,
                                   "args": [list_addr, 1, 0]}], settle=1.5)
    status = client.status()
    print(json.dumps({"status": row.get("status"), "returned_eip": row.get("returned_eip"),
                      "alive": row.get("process_alive_after"),
                      "state": status.get("state")}, ensure_ascii=False, indent=2))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
