"""Identify what the client's window thread is waiting on.

Reads dwords near the thread's ESP, treats plausible values as handles and asks
NtQueryObject for the object type/name.

    python tools/client_wait.py --name codol1649370-offline
"""
from __future__ import annotations

import argparse
import ctypes as C
import struct
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
ntdll = C.WinDLL("ntdll")


class THREADENTRY32(C.Structure):
    _fields_ = [
        ("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ThreadID", W.DWORD),
        ("th32OwnerProcessID", W.DWORD), ("tpBasePri", W.LONG), ("tpDeltaPri", W.LONG),
        ("dwFlags", W.DWORD),
    ]


class CONTEXT(C.Structure):
    _fields_ = [
        ("ContextFlags", W.DWORD),
        ("Dr0", W.DWORD), ("Dr1", W.DWORD), ("Dr2", W.DWORD), ("Dr3", W.DWORD),
        ("Dr6", W.DWORD), ("Dr7", W.DWORD),
        ("FloatSave", C.c_ubyte * 112),
        ("SegGs", W.DWORD), ("SegFs", W.DWORD), ("SegEs", W.DWORD), ("SegDs", W.DWORD),
        ("Edi", W.DWORD), ("Esi", W.DWORD), ("Ebx", W.DWORD), ("Edx", W.DWORD),
        ("Ecx", W.DWORD), ("Eax", W.DWORD), ("Ebp", W.DWORD), ("Eip", W.DWORD),
        ("SegCs", W.DWORD), ("EFlags", W.DWORD), ("Esp", W.DWORD), ("SegSs", W.DWORD),
        ("ExtendedRegisters", C.c_ubyte * 512),
    ]


class UNICODE_STRING(C.Structure):
    _fields_ = [("Length", W.USHORT), ("MaximumLength", W.USHORT), ("Buffer", C.c_void_p)]


OBJECT_NAME_INFORMATION = 1
OBJECT_TYPE_INFORMATION = 2


def find_pid(name: str) -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return 0


def window_thread(pid: int) -> int:
    user32 = C.WinDLL("user32")
    found = []

    @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def callback(hwnd, lparam):
        owner = W.DWORD(0)
        tid = user32.GetWindowThreadProcessId(hwnd, C.byref(owner))
        if owner.value == pid and tid:
            found.append(int(tid))
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else 0


def query(handle: int, info_class: int) -> str:
    buf = C.create_string_buffer(0x1000)
    ret = W.DWORD(0)
    status = ntdll.NtQueryObject(C.c_void_p(handle), info_class, buf, 0x1000, C.byref(ret))
    if status != 0:
        return f"status={status:#x}"
    if info_class == OBJECT_TYPE_INFORMATION:
        us = UNICODE_STRING.from_buffer_copy(buf.raw[:C.sizeof(UNICODE_STRING)])
        if us.Buffer and us.Length:
            return C.wstring_at(us.Buffer, us.Length // 2)
        return "?"
    us = UNICODE_STRING.from_buffer_copy(buf.raw[:C.sizeof(UNICODE_STRING)])
    if us.Buffer and us.Length:
        return C.wstring_at(us.Buffer, us.Length // 2)
    return "<unnamed>"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="codol1649370-offline")
    args = parser.parse_args()
    pid = find_pid(args.name)
    if not pid:
        print("process not running")
        return 1
    proc = k32.OpenProcess(0x0410, False, pid)
    tid = window_thread(pid)
    if not tid:
        print("no window thread")
        return 1
    handle = k32.OpenThread(0x0002 | 0x0008 | 0x0040, False, tid)
    k32.SuspendThread(handle)
    ctx = CONTEXT()
    ctx.ContextFlags = 0x00010001
    getter = getattr(k32, "Wow64GetThreadContext", None) or k32.GetThreadContext
    getter(handle, C.byref(ctx))
    buf = C.create_string_buffer(0x200)
    got = C.c_size_t(0)
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.ReadProcessMemory(proc, C.c_void_p(ctx.Esp), buf, 0x200, C.byref(got))
    print(f"pid={pid} tid={tid} eip={ctx.Eip:#x} esp={ctx.Esp:#x}")
    data = buf.raw[:got.value]
    for off in range(0, min(len(data) - 4, 0x40), 4):
        val = struct.unpack_from("<I", data, off)[0]
        if val in (0, 0xFFFFFFFF) or val > 0x10000:
            continue
        kind = query(val, OBJECT_TYPE_INFORMATION)
        name = query(val, OBJECT_NAME_INFORMATION) if kind == "Event" or kind == "Mutant" else ""
        print(f"  esp+{off:#04x} = {val:#x}  type={kind} name={name}")
    k32.ResumeThread(handle)
    k32.CloseHandle(handle)
    k32.CloseHandle(proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
