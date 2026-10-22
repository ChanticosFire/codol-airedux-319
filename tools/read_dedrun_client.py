"""Read the 2697 dedrun client ACK state from the server process memory.

The 1649370 client stops at phase 8 and never sends the reliable
acknowledgement the server waits for.  The bridge can send it instead, but it
must know how many reliable commands the server has queued.  This tool finds
the connected client's `client_t` by its decoded name and reads the fields
after `name`:

    name[36] + clantag[16] + whitelist[128] + ... + userinfo[1024]
    + reliableCommands[256 * (4 + 1024)]
    -> reliableSequence / reliableAcknowledge / reliableSent / state

    python tools/read_dedrun_client.py --name AdministraClient
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.ReadProcessMemory.restype = W.BOOL
k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t]
k32.VirtualQueryEx.restype = C.c_size_t

MEM_COMMIT = 0x1000
PAGE_READABLE = (0x02, 0x04, 0x20, 0x40, 0x80)  # RO/RW/WC/EXEC_R/EXEC_RW
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

OFF_RELIABLE_SEQUENCE = 265420
OFF_RELIABLE_ACK = 265424
OFF_RELIABLE_SENT = 265428


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("RegionSize", C.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def find_pid() -> int:
    import subprocess
    out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True, text=True,
                         errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("codol_dedrun") and parts[1].isdigit():
            return int(parts[1])
    return 0


def read(handle, address: int, size: int) -> bytes | None:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got)):
        return None
    return buf.raw[:got.value]


def iter_regions(handle) -> list[tuple[int, int]]:
    regions = []
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    while address < 0x80000000:
        size = k32.VirtualQueryEx(handle, C.c_void_p(address), C.byref(mbi), C.sizeof(mbi))
        if not size:
            break
        base = int(mbi.BaseAddress or 0)
        region = int(mbi.RegionSize)
        if region <= 0:
            break
        if (mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in PAGE_READABLE
                and not (mbi.Protect & PAGE_GUARD)):
            regions.append((base, region))
        address = base + region
    return regions


def find_name(handle, needle: bytes) -> list[int]:
    hits = []
    for base, size in iter_regions(handle):
        offset = 0
        while offset < size:
            chunk = min(0x100000, size - offset)
            data = read(handle, base + offset, chunk)
            if data:
                start = 0
                while True:
                    pos = data.find(needle, start)
                    if pos < 0:
                        break
                    hits.append(base + offset + pos)
                    start = pos + 1
            offset += chunk
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="AdministraClient")
    parser.add_argument("--out", default="runs/dedrun-client-state.json")
    args = parser.parse_args()
    pid = find_pid()
    if not pid:
        raise SystemExit("dedrun process not found")
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    result: dict = {"pid": pid, "name": args.name, "hits": [], "state": None}
    try:
        hits = find_name(handle, args.name.encode() + b"\0")
        result["hits"] = [hex(hit) for hit in hits[:20]]
        for hit in hits:
            block = read(handle, hit + OFF_RELIABLE_SEQUENCE, 24)
            if not block or len(block) < 16:
                continue
            values = struct.unpack_from("<6i", block, 0)
            candidate = {
                "name_address": hex(hit),
                "reliableSequence": values[0],
                "reliableAcknowledge": values[1],
                "reliableSent": values[2],
                "messageAcknowledge": values[3],
                "gamestateMessageNum": values[4],
                "challenge": values[5],
            }
            result["hits_detail"] = result.get("hits_detail", []) + [candidate]
            if (0 < values[0] < 100000 and -1 <= values[1] <= values[0]
                    and abs(values[4]) < 0x100000):
                result["state"] = candidate
                break
    finally:
        k32.CloseHandle(handle)
    import pathlib
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
