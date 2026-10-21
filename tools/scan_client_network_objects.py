"""Scan a running 1649370 process for the network object vtable 0xC7AF2C."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import sys
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t]


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("RegionSize", C.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client process not found")


def main() -> int:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else find_pid()
    handle = k32.OpenProcess(0x0410, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed: {C.get_last_error()}")
    pattern = struct.pack("<I", 0xC7AF2C)
    found = []
    address = 0x10000
    maximum = 0x7FFFFFFF
    mbi = MEMORY_BASIC_INFORMATION()
    while address < maximum:
        if not k32.VirtualQueryEx(handle, C.c_void_p(address), C.byref(mbi), C.sizeof(mbi)):
            break
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize or 0)
        if size <= 0:
            break
        if mbi.State == 0x1000 and (mbi.Protect & 0xFF) in (0x02, 0x04, 0x40, 0x80):
            offset = 0
            while offset < size:
                chunk = min(0x100000, size - offset)
                buffer = C.create_string_buffer(chunk)
                got = C.c_size_t()
                if (k32.ReadProcessMemory(handle, C.c_void_p(base + offset), buffer, chunk, C.byref(got))
                        and got.value >= 4):
                    data = buffer.raw[:got.value]
                    pos = data.find(pattern)
                    while pos >= 0:
                        found.append(base + offset + pos)
                        pos = data.find(pattern, pos + 1)
                offset += chunk
        address = base + size
    k32.CloseHandle(handle)
    print(json.dumps({"pid": pid, "vtable": "0xC7AF2C", "objects": [hex(x) for x in found],
                      "count": len(found)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
