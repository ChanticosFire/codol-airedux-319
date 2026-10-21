"""Patch shell32 browser-launch exports in the full 1649370 client process.

This is a private-runtime experiment: it saves the original bytes and patches
ShellExecuteA/W and ShellExecuteExA/W to return success without launching a
browser. It does not touch any file on disk.
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
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
k32.CreateToolhelp32Snapshot.restype = W.HANDLE
k32.Module32FirstW.argtypes = [W.HANDLE, C.c_void_p]
k32.Module32NextW.argtypes = [W.HANDLE, C.c_void_p]


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
    raise SystemExit("full client process not found")


def modules(pid: int) -> dict[str, int]:
    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)
    if snap in (0, W.HANDLE(-1).value):
        raise SystemExit(f"snapshot failed {C.get_last_error()}")
    entry = MODULEENTRY32W()
    entry.dwSize = C.sizeof(entry)
    found = {}
    if k32.Module32FirstW(snap, C.byref(entry)):
        while True:
            found[entry.szModule.lower()] = C.cast(entry.modBaseAddr, C.c_void_p).value
            if not k32.Module32NextW(snap, C.byref(entry)):
                break
    k32.CloseHandle(snap)
    return found


def export_rva(path: str, name: str) -> int:
    pe = pefile.PE(path, fast_load=False)
    for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if symbol.name and symbol.name.decode().lower() == name.lower():
            return symbol.address
    raise SystemExit(f"export not found: {name} in {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("evidence/experiments/tp-shell-hook.json"))
    args = parser.parse_args()
    pid = find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess {C.get_last_error()}")
    mods = modules(pid)
    shell = next((base for name, base in mods.items() if name == "shell32.dll"), None)
    if not shell:
        raise SystemExit(f"shell32 not loaded; modules={sorted(mods)[:20]}")
    host_shell = r"C:\Windows\SysWOW64\shell32.dll"
    result = {"pid": pid, "shell32": hex(shell), "patches": []}
    specs = [
        ("ShellExecuteA", b"\xb8\x21\x00\x00\x00\xc2\x18\x00", "shell32"),
        ("ShellExecuteW", b"\xb8\x21\x00\x00\x00\xc2\x18\x00", "shell32"),
        ("ShellExecuteExA", b"\xb8\x01\x00\x00\x00\xc2\x04\x00", "shell32"),
        ("ShellExecuteExW", b"\xb8\x01\x00\x00\x00\xc2\x04\x00", "shell32"),
        ("CreateProcessA", b"\x31\xc0\xc2\x28\x00", "kernel32"),
        ("CreateProcessW", b"\x31\xc0\xc2\x28\x00", "kernel32"),
    ]
    kernel = next((base for name, base in mods.items() if name == "kernel32.dll"), None)
    hosts = {"shell32": r"C:\Windows\SysWOW64\shell32.dll",
             "kernel32": r"C:\Windows\SysWOW64\kernel32.dll"}
    bases = {"shell32": shell, "kernel32": kernel}
    for name, patch, module in specs:
        base = bases.get(module)
        if not base:
            result["patches"].append({"name": name, "status": "module_missing"})
            continue
        try:
            rva = export_rva(hosts[module], name)
        except SystemExit:
            continue
        address = base + rva
        original = C.create_string_buffer(len(patch))
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(address), original, len(patch), C.byref(got)):
            result["patches"].append({"name": name, "status": "read_failed", "error": C.get_last_error()})
            continue
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(address), len(patch), 0x40, C.byref(old))
        wrote = C.c_size_t()
        ok = k32.WriteProcessMemory(handle, C.c_void_p(address), C.create_string_buffer(patch, len(patch)),
                                    len(patch), C.byref(wrote))
        k32.VirtualProtectEx(handle, C.c_void_p(address), len(patch), old.value, C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(address), len(patch))
        result["patches"].append({"name": name, "va": hex(address), "rva": hex(rva),
                                  "original": original.raw.hex(), "patched": patch.hex(),
                                  "status": "ok" if ok and wrote.value == len(patch) else "write_failed"})
    result["time"] = time.time()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
