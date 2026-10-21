"""Read-only VEH trace of the 0xC73900 entry (PAGE_GUARD, no call replacement)."""
from __future__ import annotations

import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W
from pathlib import Path

import pefile

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD,
                                   C.POINTER(W.DWORD)]
k32.CreateRemoteThread.restype = W.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.CreateToolhelp32Snapshot.restype = W.HANDLE
k32.Module32FirstW.argtypes = [W.HANDLE, C.c_void_p]
k32.Module32NextW.argtypes = [W.HANDLE, C.c_void_p]


def pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def export_rva(path: str, name: str) -> int:
    pe = pefile.PE(path, fast_load=False)
    for s in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if s.name and s.name.decode().lower() == name.lower():
            return s.address
    raise SystemExit(name)


def modules(p: int):
    # Use a simple PEB-free approach: kernel32 base is available from the exe's IAT in this build.
    return {}


def main() -> int:
    p = pid()
    h = k32.OpenProcess(0x1F0FFF, False, p)
    cave = int(k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40))
    log = cave + 0x400
    handler = cave
    hcode = bytearray()
    hcode += b"\x8b\x44\x24\x04"                    # mov eax,[esp+4]
    hcode += b"\x8b\x08"                            # mov ecx,[eax]
    hcode += b"\x8b\x51\x0c"                        # mov edx,[ecx+0xc]
    hcode += b"\x89\x15" + struct.pack("<I", log)   # [log]=ExceptionAddress
    hcode += b"\x8b\x48\x04"                        # mov ecx,[eax+4] context
    hcode += b"\x8b\x91\xc4\x00\x00\x00"            # mov edx,[ecx+0xc4] Esp
    hcode += b"\x89\x15" + struct.pack("<I", log + 4)
    hcode += b"\x8b\x81\xb8\x00\x00\x00"            # mov eax,[ecx+0xb8] Eip
    hcode += b"\xa3" + struct.pack("<I", log + 8)
    for i in range(4):
        hcode += b"\x8b\x42" + bytes([4 + i * 4])   # mov eax,[edx+4+4i]
        hcode += b"\xa3" + struct.pack("<I", log + 0xC + i * 4)
    hcode += b"\xb8\xff\xff\xff\xff"                # mov eax,-1
    hcode += b"\xc2\x04\x00"                        # ret 4
    w = C.c_size_t()
    k32.WriteProcessMemory(h, C.c_void_p(cave), C.create_string_buffer(bytes(hcode), len(hcode)),
                           len(hcode), C.byref(w))
    kernel = 0x74E00000  # updated below from the target module list if needed
    # Find kernel32 base via the game's IAT is unreliable; use a known 32-bit export address from the host image.
    import pefile as _pe
    host = _pe.PE(r"C:\Windows\SysWOW64\kernel32.dll", fast_load=False)
    addveh_rva = next(s.address for s in host.DIRECTORY_ENTRY_EXPORT.symbols
                      if s.name and s.name.decode().lower() == "addvectoredexceptionhandler")
    # kernel32 base is resolved by scanning the process modules with toolhelp.
    class ME(C.Structure):
        _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD),
                    ("modBaseAddr", C.c_void_p), ("modBaseSize", W.DWORD), ("hModule", W.HMODULE),
                    ("szModule", W.WCHAR * 256), ("szExePath", W.WCHAR * 260)]
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, p)
    me = ME(); me.dwSize = C.sizeof(me)
    base = 0
    if k32.Module32FirstW(snap, C.byref(me)):
        while True:
            if me.szModule.lower() == "kernel32.dll":
                base = me.modBaseAddr or 0
                break
            if not k32.Module32NextW(snap, C.byref(me)):
                break
    k32.CloseHandle(snap)
    addveh = base + addveh_rva
    inst = b"\x6a\x01\x68" + struct.pack("<I", handler) + b"\xe8" + \
        struct.pack("<i", addveh - (cave + 0x100 + 12)) + b"\xc3"
    k32.WriteProcessMemory(h, C.c_void_p(cave + 0x100), C.create_string_buffer(inst, len(inst)),
                           len(inst), C.byref(w))
    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, C.c_void_p(cave + 0x100), None, 0, C.byref(tid))
    k32.WaitForSingleObject(th, 3000)
    old = W.DWORD()
    ok = k32.VirtualProtectEx(h, C.c_void_p(0xC73000), 0x1000, 0x120, C.byref(old))
    out = {"pid": p, "cave": hex(cave), "kernel32": hex(base), "addveh": hex(addveh),
           "guard": bool(ok), "guard_error": None if ok else C.get_last_error()}
    time.sleep(10)
    buf = C.create_string_buffer(0x1C)
    g = C.c_size_t()
    k32.ReadProcessMemory(h, C.c_void_p(log), buf, 0x1C, C.byref(g))
    out["log"] = [hex(x) for x in struct.unpack("<7I", buf.raw)]
    Path("evidence/experiments/c73900-veh.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
