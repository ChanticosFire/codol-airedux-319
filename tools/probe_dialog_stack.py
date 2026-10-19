#!/usr/bin/env python
"""Read-only stack attribution for the WIN_NO_TCLS fatal dialog.

When the dialog is up, the owning thread is blocked inside user32's message
box. This tool suspends that thread, reads its WOW64 context through
Wow64GetThreadContext, walks the raw stack for return addresses that fall
inside executable modules, and disassembles a short window around each hit.

It never writes to the target and resumes the thread before termination.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
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
THREAD_GET_CONTEXT = 0x0008
THREAD_QUERY_INFORMATION = 0x0040
THREAD_SUSPEND_RESUME = 0x0002
CONTEXT_i386 = 0x00010000
CONTEXT_CONTROL = CONTEXT_i386 | 0x00000001
CONTEXT_FULL = CONTEXT_i386 | 0x00000007
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
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


class FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [("ControlWord", wt.DWORD), ("StatusWord", wt.DWORD), ("TagWord", wt.DWORD),
                ("ErrorOffset", wt.DWORD), ("ErrorSelector", wt.DWORD), ("DataOffset", wt.DWORD),
                ("DataSelector", wt.DWORD), ("RegisterArea", ctypes.c_byte * 80),
                ("Cr0NpxState", wt.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wt.DWORD),
        ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD), ("Dr3", wt.DWORD),
        ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
        ("FloatSave", FLOATING_SAVE_AREA),
        ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD), ("SegDs", wt.DWORD),
        ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD), ("Edx", wt.DWORD),
        ("Ecx", wt.DWORD), ("Eax", wt.DWORD),
        ("Ebp", wt.DWORD), ("Eip", wt.DWORD), ("SegCs", wt.DWORD), ("EFlags", wt.DWORD),
        ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]


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
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.SuspendThread.argtypes = [wt.HANDLE]
k32.SuspendThread.restype = wt.DWORD
k32.Wow64GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k32.Wow64GetThreadContext.restype = wt.BOOL
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
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextA.argtypes = [wt.HWND, ctypes.c_char_p, ctypes.c_int]
user32.EnumChildWindows.argtypes = [wt.HWND, ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]


def modules_of(pid: int) -> list[dict]:
    snapshot = k32.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    if snapshot == ctypes.c_void_p(-1).value:
        return []
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        items = []
        if not k32.Module32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
            items.append({"name": entry.szModule, "base": base, "size": entry.modBaseSize})
            if not k32.Module32NextW(snapshot, ctypes.byref(entry)):
                break
        return items
    finally:
        k32.CloseHandle(snapshot)


def read_memory(process, address: int, size: int):
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    if k32.ReadProcessMemory(process, ctypes.c_void_p(address), buffer, size, ctypes.byref(read)):
        return buffer.raw[: read.value]
    return None


def find_dialog(pid: int):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _lparam):
        owner = wt.DWORD(0)
        tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, cls, len(cls))
        if cls.value != "#32770":
            return True
        texts = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def child(child_hwnd, _lp):
            buffer = ctypes.create_string_buffer(1024)
            user32.GetWindowTextA(child_hwnd, buffer, len(buffer))
            if buffer.value:
                texts.append(buffer.value.decode("gbk", "replace"))
            return True

        user32.EnumChildWindows(hwnd, child, 0)
        found.append({"hwnd": int(hwnd), "thread_id": tid, "children": texts})
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def owner_of(modules: list[dict], address: int):
    for module in modules:
        base = module["base"]
        if base and base <= address < base + module["size"]:
            return module["name"], address - base
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--extra-args", default="", help="command-line switches appended verbatim, e.g. -q")
    args = parser.parse_args()
    root = args.client_dir.resolve(strict=True)
    if root != (REPO_ROOT / "runtime" / "client-1649370").resolve():
        print("refusing: not the owned staged copy", file=sys.stderr)
        return 2
    checks = verify_client(root)
    if not all(check.ok for check in checks):
        print("refusing: anchor mismatch", file=sys.stderr)
        return 2
    exe = root / "codoMP_client_shipRetail.exe"
    command_line = f'"{exe}"' + (f" {args.extra_args}" if args.extra_args else "")
    si = STARTUPINFOW(); si.cb = ctypes.sizeof(STARTUPINFOW)
    pi = PROCESS_INFORMATION()
    if not k32.CreateProcessW(str(exe), ctypes.create_unicode_buffer(command_line), None, None, False,
                              CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, None, str(root),
                              ctypes.byref(si), ctypes.byref(pi)):
        print("CreateProcessW failed", ctypes.get_last_error(), file=sys.stderr)
        return 2
    pid = pi.dwProcessId
    record = {"build": BUILD, "pid": pid, "command_line": command_line, "dialog": None, "context": None,
              "stack": [], "modules": [],
              "notes": ["read-only: VM_READ + thread context; no writes"]}
    evidence = args.evidence.resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    try:
        k32.ResumeThread(pi.hThread)
        dialog = None
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(0.25)
            dialog = find_dialog(pid)
            if dialog:
                break
        record["dialog"] = dialog
        if not dialog:
            record["error"] = "dialog not observed"
            return 3
        modules = modules_of(pid)
        record["modules"] = [{"name": m["name"], "base": hex(m["base"]), "size": m["size"]} for m in modules if m["base"]]
        thread = k32.OpenThread(THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION | THREAD_SUSPEND_RESUME,
                                False, dialog["thread_id"])
        if not thread:
            record["error"] = "OpenThread failed"
            return 3
        try:
            k32.SuspendThread(thread)
            context = WOW64_CONTEXT()
            context.ContextFlags = CONTEXT_FULL
            if not k32.Wow64GetThreadContext(thread, ctypes.byref(context)):
                record["error"] = f"Wow64GetThreadContext failed {ctypes.get_last_error()}"
                return 3
            record["context"] = {"eip": hex(context.Eip), "esp": hex(context.Esp), "ebp": hex(context.Ebp)}
            process = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
            if not process:
                record["error"] = "OpenProcess failed"
                return 3
            try:
                # Precise walk: [ebp] = previous frame, [ebp+4] = return address.
                chain = []
                frame_pointer = context.Ebp
                seen = set()
                for _ in range(48):
                    if frame_pointer in seen or frame_pointer < 0x10000 or frame_pointer > 0x7FFFFFFF:
                        break
                    seen.add(frame_pointer)
                    frame = read_memory(process, frame_pointer, 8)
                    if not frame:
                        break
                    previous, return_address = int.from_bytes(frame[0:4], "little"), int.from_bytes(frame[4:8], "little")
                    name, offset = owner_of(modules, return_address)
                    chain.append({"ebp": hex(frame_pointer), "return": hex(return_address),
                                  "module": name, "module_offset": hex(offset) if name else None})
                    if previous <= frame_pointer:
                        break
                    frame_pointer = previous
                record["ebp_chain"] = chain
                stack = read_memory(process, context.Esp, 2048)
                if stack:
                    candidates = []
                    for index in range(0, len(stack) - 3, 4):
                        value = int.from_bytes(stack[index:index + 4], "little")
                        name, offset = owner_of(modules, value)
                        if name:
                            candidates.append({"slot": index, "value": hex(value), "module": name,
                                               "module_offset": hex(offset)})
                    record["stack"] = candidates[:40]
                    if Cs is not None:
                        md = Cs(CS_ARCH_X86, CS_MODE_32)
                        for candidate in record["stack"][:12]:
                            address = int(candidate["value"], 16)
                            code = read_memory(process, address - 24, 64)
                            if not code:
                                continue
                            candidate["disassembly"] = [
                                f"{ins.address:#010x} {ins.mnemonic} {ins.op_str}"
                                for ins in md.disasm(code, address - 24)
                            ][:20]
                        for frame in chain:
                            address = int(frame["return"], 16)
                            code = read_memory(process, address - 16, 48)
                            if not code:
                                continue
                            frame["disassembly"] = [
                                f"{ins.address:#010x} {ins.mnemonic} {ins.op_str}"
                                for ins in md.disasm(code, address - 16)
                            ][:16]
            finally:
                k32.CloseHandle(process)
        finally:
            k32.ResumeThread(thread)
            k32.CloseHandle(thread)
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
