"""List a process's loaded modules and resolve absolute addresses to module+offset.

Round 66 found 0xBB15E0 calling through [0xCA851C] = 0x119C6A2F and taking an error code
from [0xCA853C] = 0x76BD9EF0. This enumerates modules so those addresses can be attributed,
and optionally resolves a module export by name.

    python tools/modules.py                       # list all modules
    python tools/modules.py --resolve 0x119C6A2F  # find the owning module
    python tools/modules.py --exports ws2_32.dll  # list exports of one module
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MAX_MODULE_NAME32 = 255

k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

EXE = "codomp_client_shipretail.exe"


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
        ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_char * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_char * wt.MAX_PATH),
    ]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def modules(pid: int) -> list[tuple[int, int, str, str]]:
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if not snap or snap == wt.HANDLE(-1).value:
        return []
    out: list[tuple[int, int, str, str]] = []
    entry = MODULEENTRY32()
    entry.dwSize = ctypes.sizeof(MODULEENTRY32)
    k32.Module32First.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32)]
    k32.Module32Next.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32)]
    ok = k32.Module32First(snap, ctypes.byref(entry))
    while ok:
        base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
        name = entry.szModule.decode("mbcs", "replace")
        path = entry.szExePath.decode("mbcs", "replace")
        out.append((base, entry.modBaseSize, name, path))
        ok = k32.Module32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--resolve", action="append", default=[], help="address in hex, repeatable")
    ap.add_argument("--filter", default="", help="only show modules whose name contains this")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    if not pid:
        print("client not running")
        return 2
    mods = modules(pid)
    if not mods:
        print("module enumeration failed")
        return 3
    mods.sort(key=lambda m: m[0])
    print(f"pid={pid}  modules={len(mods)}")
    if args.resolve:
        for raw in args.resolve:
            addr = int(raw, 16)
            hit = None
            for base, size, name, path in mods:
                if base <= addr < base + size:
                    hit = (base, size, name, path)
                    break
            if hit:
                base, size, name, path = hit
                print(f"  {addr:#010x} -> {name} + {addr - base:#x}  ({path})")
            else:
                print(f"  {addr:#010x} -> no owning module")
        print()
    for base, size, name, path in mods:
        if args.filter and args.filter.lower() not in name.lower():
            continue
        print(f"  {base:#010x}  size={size:#08x}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
