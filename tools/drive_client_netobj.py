"""Drive the community offline client's netobj toward a connection.

Run while the lobby is up. It creates the netobj (0x803830) and calls the
lobby tick / state functions with ecx=netobj through small remote caves.
"""
from __future__ import annotations

import ctypes as C
import json
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
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD,
                                   C.POINTER(W.DWORD)]
k32.CreateRemoteThread.restype = W.HANDLE


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("community client not running")


def u32(h, address: int) -> int:
    buf = C.create_string_buffer(4)
    got = C.c_size_t()
    k32.ReadProcessMemory(h, C.c_void_p(address), buf, 4, C.byref(got))
    return struct.unpack("<I", buf.raw)[0]


def call_cave(h, label: str, func: int, ecx: int | None = None):
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    if ecx is None:
        code = b"\xe8" + struct.pack("<i", func - (cave + 5)) + b"\xc3"
    else:
        code = b"\xb9" + struct.pack("<I", ecx) + b"\xe8" + struct.pack("<i", func - (cave + 11)) + b"\xc3"
    wrote = C.c_size_t()
    k32.WriteProcessMemory(h, C.c_void_p(cave), C.create_string_buffer(code, len(code)), len(code),
                           C.byref(wrote))
    tid = W.DWORD()
    thread = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    k32.WaitForSingleObject(thread, 3000)
    time.sleep(0.4)
    return {"label": label, "cave": hex(cave), "thread": int(thread), "tid": tid.value}


def main() -> int:
    process = pid()
    h = k32.OpenProcess(0x1F0FFF, False, process)
    result = {"pid": process, "calls": []}
    netobj = u32(h, 0x8269774)
    if not netobj:
        result["calls"].append(call_cave(h, "create_netobj", 0x803830))
        netobj = u32(h, 0x8269774)
    result["netobj_initial"] = hex(netobj)
    if not netobj:
        result["error"] = "netobj still null"
        Path("evidence/experiments/netobj-drive.json").write_text(json.dumps(result, indent=2) + "\n")
        return 1

    # 0x803780 has no this pointer; it reloads [0x8269774] itself.
    result["calls"].append(call_cave(h, "lobby_tick_803780", 0x803780))
    result["after_tick"] = {"conn": hex(u32(h, netobj + 0x4F4)),
                            "state": hex(u32(h, netobj + 0x4F8))}

    # 0xB838A0(this=ecx) is the lobby/socket entry used by 0x803780.
    for func, name in ((0xB838A0, "lobby_connect_B838A0"),
                       (0xB7A670, "state_B7A670")):
        result["calls"].append(call_cave(h, name, func, netobj))
        result[name] = {"conn": hex(u32(h, netobj + 0x4F4)),
                        "state": hex(u32(h, netobj + 0x4F8)),
                        "field_0x1F0": hex(u32(h, netobj + 0x1F0))}
    out = Path("evidence/experiments/netobj-drive.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
