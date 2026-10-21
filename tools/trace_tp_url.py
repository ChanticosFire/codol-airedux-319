"""One-shot PAGE_GUARD tracer for the TP URL string in the full 1649370 client.

No debugger: protect the URL page, install an in-process VEH that records the
faulting EIP, then read the log. The guard is one-shot, so the first reader is
captured.
"""
from __future__ import annotations

import argparse
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
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
k32.CreateRemoteThread.restype = W.HANDLE
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.CreateToolhelp32Snapshot.restype = W.HANDLE


class MODULEENTRY32W(C.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD),
                ("modBaseAddr", C.POINTER(C.c_byte)), ("modBaseSize", W.DWORD),
                ("hModule", W.HMODULE), ("szModule", W.WCHAR * 256), ("szExePath", W.WCHAR * 260)]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codoMP_client_shipRetail.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("full client not running")


def modules(pid: int):
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)
    entry = MODULEENTRY32W()
    entry.dwSize = C.sizeof(entry)
    found = []
    if k32.Module32FirstW(snap, C.byref(entry)):
        while True:
            found.append((entry.szModule.lower(), C.cast(entry.modBaseAddr, C.c_void_p).value,
                          entry.modBaseSize))
            if not k32.Module32NextW(snap, C.byref(entry)):
                break
    k32.CloseHandle(snap)
    return found


def export_rva(path: str, name: str) -> int:
    pe = pefile.PE(path, fast_load=False)
    for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if symbol.name and symbol.name.decode().lower() == name.lower():
            return symbol.address
    raise SystemExit(f"export missing {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("evidence/experiments/tp-url-trace.json"))
    parser.add_argument("--wait", type=float, default=12.0)
    args = parser.parse_args()
    pid = find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    needle = b"?a=%d&b=%d&c=%d&game_id=%d&reason_id=%d"
    result = {"pid": pid, "needle": needle.decode(), "hits": []}
    for name, base, size in modules(pid):
        offset = 0
        while offset < size:
            chunk = min(0x100000, size - offset)
            buf = C.create_string_buffer(chunk)
            got = C.c_size_t()
            if k32.ReadProcessMemory(handle, C.c_void_p(base + offset), buf, chunk, C.byref(got)):
                data = buf.raw[:got.value]
                pos = data.find(needle)
                while pos >= 0:
                    result["hits"].append({"module": name, "address": hex(base + offset + pos)})
                    pos = data.find(needle, pos + 1)
            offset += chunk
    if not result["hits"]:
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 1
    target = int(result["hits"][0]["address"], 16)
    page = target & ~0xFFF
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    log = cave + 0x300
    handler = cave
    # handler(EXCEPTION_POINTERS*): log ExceptionAddress and Context.Eip, continue execution
    h = bytearray()
    h += b"\x8b\x44\x24\x04"                    # mov eax,[esp+4]
    h += b"\x8b\x08"                            # mov ecx,[eax]
    h += b"\x8b\x51\x0c"                        # mov edx,[ecx+0xc]
    h += b"\x89\x15" + struct.pack("<I", log)   # mov [log],edx
    h += b"\x8b\x48\x04"                        # mov ecx,[eax+4]
    h += b"\x8b\x91\xb8\x00\x00\x00"            # mov edx,[ecx+0xb8]
    h += b"\x89\x15" + struct.pack("<I", log + 4)
    h += b"\xb8\xff\xff\xff\xff"                # mov eax,-1
    h += b"\xc2\x04\x00"                        # ret 4
    k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(bytes(h), len(h)), len(h),
                           C.byref(C.c_size_t()))
    kernel = next((base for name, base, _ in modules(pid) if name == "kernel32.dll"), 0)
    addveh = kernel + export_rva(r"C:\Windows\SysWOW64\kernel32.dll", "AddVectoredExceptionHandler")
    installer = b"\x6a\x01\x68" + struct.pack("<I", handler) + b"\xe8" + \
        struct.pack("<i", addveh - (cave + 0x100 + 12)) + b"\xc3"
    k32.WriteProcessMemory(handle, C.c_void_p(cave + 0x100), C.create_string_buffer(installer, len(installer)),
                           len(installer), C.byref(C.c_size_t()))
    tid = W.DWORD()
    thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave + 0x100), None, 0, C.byref(tid))
    k32.WaitForSingleObject(thread, 5000)
    old = W.DWORD()
    ok = k32.VirtualProtectEx(handle, C.c_void_p(page), 0x1000, 0x102, C.byref(old))
    result["guard_set"] = bool(ok)
    result["guard_error"] = None if ok else C.get_last_error()
    time.sleep(args.wait)
    logbuf = C.create_string_buffer(8)
    got = C.c_size_t()
    k32.ReadProcessMemory(handle, C.c_void_p(log), logbuf, 8, C.byref(got))
    exc, eip = struct.unpack("<II", logbuf.raw)
    result.update({"page": hex(page), "cave": hex(cave), "handler": hex(handler),
                   "addveh": hex(addveh), "exception_address": hex(exc), "eip": hex(eip),
                   "module_base": next((hex(base) for name, base, size in modules(pid)
                                        if base <= eip < base + size), None),
                   "module_offset": None})
    for name, base, size in modules(pid):
        if base <= eip < base + size:
            result["module_name"] = name
            result["module_offset"] = hex(eip - base)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
