"""Make the client load the gametype fastfile via Com_LoadFastfiles (0x49E160).

    python tools/load_gametype.py [--name common_gametype_mp]

Reproduces what LoadDemo (0x49E600) does internally at 0x49E982: build a 4-entry
list with 0x49E540's layout and call 0x49E160(list, 4, 0).

List layout (verified from 0x49E540):
    u32 count = 4
    entry[0] = { char* "patch_<name>";            u32 4; u32 0 }
    entry[1] = { char* "<name>";                  u32 4; u32 0 }
    entry[2] = { char* "patch_localized_<name>";  u32 4; u32 0 }
    entry[3] = { char* "localized_<name>";        u32 4; u32 0 }
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
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
ENTRY = 12


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="common_gametype_mp")
    ap.add_argument("--mode", type=lambda v: int(v, 0), default=0)
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()

    client = Client()
    base = int(k32.VirtualAllocEx(client.handle, None, 0x2000, 0x3000, 0x04) or 0)
    if not base:
        raise SystemExit("VirtualAllocEx failed")

    names = [f"patch_{args.name}", args.name,
             f"patch_localized_{args.name}", f"localized_{args.name}"]
    def write(address: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(client.handle, C.c_void_p(address),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    name_addr = []
    cursor = base + 0x400
    for text in names:
        name_addr.append(cursor)
        if not write(cursor, text.encode() + b"\0"):
            raise SystemExit("write name failed")
        cursor += 0x100

    list_addr = base
    blob = struct.pack("<I", 4)
    for address in name_addr:
        blob += struct.pack("<III", address, 4, 0)
    if not write(list_addr, blob):
        raise SystemExit("write list failed")

    row = client.invoke_sequence([{"target": LOAD_FASTFILES,
                                   "args": [list_addr, 4, args.mode]}], settle=args.settle)
    status = client.status()
    print(json.dumps({"names": names, "status": row.get("status"),
                      "returned_eip": row.get("returned_eip"),
                      "alive": row.get("process_alive_after"),
                      "state": status.get("state")}, ensure_ascii=True, indent=2))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
