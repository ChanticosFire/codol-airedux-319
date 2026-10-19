#!/usr/bin/env python
"""Read-only runtime probe for the WIN_NO_TCLS gate.

The launcher starts the client, waits until the fatal dialog appears, then
opens the process with PROCESS_VM_READ only and records:

  * module bases/sizes (Toolhelp32, works across WOW64),
  * in-memory occurrences of the TCLS anchor strings,
  * absolute 32-bit references to those strings inside executable regions,
  * a short disassembly around each reference.

It never writes to the target, never injects, never changes protection and
never touches the protected sections. The process is terminated afterwards,
only when its image lives under the owned staged copy.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server319.manifest import BUILD, verify_client  # noqa: E402

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:  # pragma: no cover
    Cs = None

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_TERMINATE = 0x0001
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

ANCHORS = [b"WIN_NO_TCLS", b"TCLS_SHAREDMEMEMORY", b"TCLS_TASMEMORY_", b"TenP_TS_"]
TEXT_SECTION_FLAGS = 0x20000000 | 0x00000020  # IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_CNT_CODE

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)), ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE), ("szModule", wt.WCHAR * 256), ("szExePath", wt.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                               wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                               ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
k32.CreateProcessW.restype = wt.BOOL
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                               ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.Module32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.Module32FirstW.restype = wt.BOOL
k32.Module32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.Module32NextW.restype = wt.BOOL
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextA.argtypes = [wt.HWND, ctypes.c_char_p, ctypes.c_int]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def modules_of(pid: int) -> list[dict]:
    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snapshot == ctypes.c_void_p(-1).value:
        return []
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        items = []
        if not k32.Module32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            items.append({"name": entry.szModule, "base": ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value,
                          "size": entry.modBaseSize, "path": entry.szExePath})
            if not k32.Module32NextW(snapshot, ctypes.byref(entry)):
                break
        return items
    finally:
        k32.CloseHandle(snapshot)


def regions_of(process) -> list[dict]:
    regions = []
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    while k32.VirtualQueryEx(process, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        size = mbi.RegionSize or 0
        if size == 0:
            break
        readable = (mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD)
                    and (mbi.Protect & 0xFF) not in (PAGE_NOACCESS,))
        if readable:
            regions.append({"base": mbi.BaseAddress or 0, "size": size,
                            "protect": mbi.Protect, "type": mbi.Type})
        address += size
        if address > 0x7FFFFFFF:
            break
    return regions


def read_memory(process, address: int, size: int) -> bytes | None:
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    if k32.ReadProcessMemory(process, ctypes.c_void_p(address), buffer, size, ctypes.byref(read)):
        return buffer.raw[: read.value]
    return None


def find_dialog(pid: int) -> dict | None:
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _lparam):
        owner = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        class_buffer = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        if class_buffer.value != "#32770":
            return True
        # Collect the dialog and its child static texts with the ANSI API.
        texts = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def child(child_hwnd, _lp):
            buffer = ctypes.create_string_buffer(1024)
            user32.GetWindowTextA(child_hwnd, buffer, len(buffer))
            if buffer.value:
                texts.append(buffer.value.decode("gbk", "replace"))
            return True

        user32.EnumChildWindows(hwnd, child, 0)
        title = ctypes.create_string_buffer(512)
        user32.GetWindowTextA(hwnd, title, len(title))
        found.append({"hwnd": int(hwnd), "title": title.value.decode("gbk", "replace"), "children": texts})
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--args", default="")
    args = parser.parse_args()
    root = args.client_dir.resolve(strict=True)
    staged = (REPO_ROOT / "runtime" / "client-1649370").resolve()
    if root != staged:
        print("refusing: not the owned staged copy", file=sys.stderr)
        return 2
    checks = verify_client(root)
    if not all(check.ok for check in checks):
        print("refusing: anchor mismatch", file=sys.stderr)
        return 2
    exe = root / "codoMP_client_shipRetail.exe"
    command = f'"{exe}"' + (" " + args.args if args.args else "")
    si = STARTUPINFOW(); si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    if not k32.CreateProcessW(str(exe), ctypes.create_unicode_buffer(command), None, None, False,
                              CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, None, str(root),
                              ctypes.byref(si), ctypes.byref(pi)):
        print("CreateProcessW failed", ctypes.get_last_error(), file=sys.stderr)
        return 2
    pid = pi.dwProcessId
    record = {"build": BUILD, "pid": pid, "command_line": command, "dialog": None,
              "modules": [], "anchors": [], "notes": [
                  "read-only: PROCESS_VM_READ; no writes, no injection",
                  "absolute 32-bit references only; protected or calculated references may be missed"]}
    evidence = args.evidence.resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    try:
        k32.ResumeThread(pi.hThread)
        deadline = time.time() + args.timeout
        dialog = None
        while time.time() < deadline:
            time.sleep(0.25)
            dialog = find_dialog(pid)
            if dialog:
                break
        record["dialog"] = dialog
        process = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not process:
            record["error"] = "OpenProcess failed"
            return 3
        try:
            modules = modules_of(pid)
            record["modules"] = [{"name": m["name"], "base": hex(m["base"]), "size": m["size"]} for m in modules if m["base"]]
            regions = regions_of(process)
            record["region_count"] = len(regions)
            # 1. find anchor strings in memory
            hits = []
            for region in regions:
                data = read_memory(process, region["base"], min(region["size"], 64 * 1024 * 1024))
                if not data:
                    continue
                for anchor in ANCHORS:
                    start = 0
                    while True:
                        index = data.find(anchor, start)
                        if index < 0:
                            break
                        start = index + 1
                        hits.append({"anchor": anchor.decode(), "va": region["base"] + index,
                                     "region_base": region["base"], "protect": region["protect"]})
            # 2. find absolute references to the string VAs in executable regions
            for hit in hits[:40]:
                needle = struct.pack("<I", hit["va"] & 0xFFFFFFFF)
                refs = []
                for region in regions:
                    if not (region["protect"] & 0x10 or region["protect"] & 0x20 or region["protect"] & 0x40):
                        continue
                    data = read_memory(process, region["base"], min(region["size"], 32 * 1024 * 1024))
                    if not data:
                        continue
                    start = 0
                    while True:
                        index = data.find(needle, start)
                        if index < 0:
                            break
                        start = index + 1
                        refs.append(region["base"] + index)
                        if len(refs) >= 40:
                            break
                hit["absolute_reference_count"] = len(refs)
                hit["absolute_reference_va"] = [hex(value) for value in refs[:20]]
                if Cs is not None and refs:
                    md = Cs(CS_ARCH_X86, CS_MODE_32)
                    windows = []
                    for ref in refs[:10]:
                        # disassemble 32 bytes ending at the reference
                        start_address = ref - 24
                        code = read_memory(process, start_address, 48)
                        if not code:
                            continue
                        lines = [f"{ins.address:#010x} {ins.mnemonic} {ins.op_str}" for ins in md.disasm(code, start_address)]
                        windows.append({"ref": hex(ref), "window": lines})
                    hit["disassembly"] = windows
                record["anchors"].append(hit)
        finally:
            k32.CloseHandle(process)
    finally:
        handle = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            k32.TerminateProcess(handle, 1)
            k32.CloseHandle(handle)
        evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
