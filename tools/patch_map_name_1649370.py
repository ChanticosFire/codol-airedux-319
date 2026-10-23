"""Write the current map name into the 1649370 UI/game object field.

State-10 bring-up reads ``[0x333A8EC] + 0xC`` and skips the game/UI
initialisation when that string is empty (0x515D69).  This tool reports the
object and can patch the buffer, so the gate can be tested without a full
gamestate rewrite.

Usage:
    python tools/patch_map_name_1649370.py --name mp_cross_fire
    python tools/patch_map_name_1649370.py --name mp_cross_fire --output runs/patch.json
"""
from __future__ import annotations

import argparse
import ctypes as C
import ctypes.wintypes as W
import json
import struct
import subprocess
from pathlib import Path

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                   C.POINTER(C.c_size_t)]
k32.CloseHandle.argtypes = [W.HANDLE]

EXE = "codol1649370-offline.exe"
OBJECT_SLOT = 0x333A8EC
MAP_OFFSET = 0xC
UI_STATE = 0x84ABA50
STATE = 0x76446B0


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="mp_cross_fire")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pid", type=int, default=0)
    args = parser.parse_args()
    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        print(f"OpenProcess failed: {C.get_last_error()}")
        return 3

    def u32(address: int) -> int:
        buf = C.create_string_buffer(4)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, 4, C.byref(got)):
            raise OSError(f"read {address:#x}")
        return struct.unpack("<I", buf.raw)[0]

    def cstring(address: int, limit: int = 128) -> str:
        buf = C.create_string_buffer(limit)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), buf, limit, C.byref(got)):
            return ""
        return buf.raw.split(b"\0", 1)[0].decode("latin-1", "replace")

    try:
        obj = u32(OBJECT_SLOT)
        pointer = u32(obj + MAP_OFFSET) if obj else 0
        before = cstring(pointer) if pointer else ""
        report = {
            "pid": pid, "ui_state": u32(UI_STATE), "state": u32(STATE),
            "object_slot": hex(OBJECT_SLOT), "object": hex(obj),
            "map_pointer": hex(pointer) if pointer else None, "map_before": before,
        }
        if pointer:
            text = args.name.encode("latin-1") + b"\0"
            got = C.c_size_t()
            ok = k32.WriteProcessMemory(handle, C.c_void_p(pointer),
                                        C.create_string_buffer(text, len(text)),
                                        len(text), C.byref(got))
            report["write_ok"] = bool(ok)
            report["map_after"] = cstring(pointer)
            report["ui_state_after"] = u32(UI_STATE)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
