"""Report where the client's threads are executing (EIP) by sampling contexts.

    python tools/client_eip.py --name codol1649370-offline

For every thread of the process it prints the EIP and, when the address falls
inside the main module, the file VA (module base subtracted) so it can be
matched against the static analysis addresses.
"""
from __future__ import annotations

import argparse
import ctypes as C
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)

TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
THREAD_GET_CONTEXT = 0x0008
THREAD_QUERY_INFORMATION = 0x0040
CONTEXT_i386 = 0x00010000
CONTEXT_CONTROL = CONTEXT_i386 | 0x00000001


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


def find_pid(name: str) -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return 0


def module_base(pid: int) -> int:
    import ctypes as C2
    from ctypes import wintypes as W2
    psapi = C2.WinDLL("psapi")
    proc = k32.OpenProcess(0x0410, False, pid)
    psapi.EnumProcessModules.argtypes = [W2.HANDLE, C2.POINTER(C2.c_void_p), W2.DWORD, C2.POINTER(W2.DWORD)]
    need = W2.DWORD(0)
    arr = (C2.c_void_p * 256)()
    psapi.EnumProcessModules(proc, arr, C2.sizeof(arr), C2.byref(need))
    k32.CloseHandle(proc)
    return arr[0] if need.value else 0


def window_thread(pid: int) -> int:
    """Return the thread id that owns a top-level window of the given process."""
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="codol1649370-offline")
    parser.add_argument("--stack", action="store_true", help="scan each thread stack for client return addresses")
    parser.add_argument("--frames", action="store_true", help="walk the EBP chain of the window thread")
    args = parser.parse_args()
    pid = find_pid(args.name)
    if not pid:
        print("process not running")
        return 1
    base = module_base(pid)
    proc = k32.OpenProcess(0x0410, False, pid)
    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32()
    entry.dwSize = C.sizeof(THREADENTRY32)
    rows = []
    ok = k32.Thread32First(snapshot, C.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == pid:
            handle = k32.OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
                                    False, entry.th32ThreadID)
            if handle:
                k32.SuspendThread(handle)
                ctx = CONTEXT()
                ctx.ContextFlags = CONTEXT_CONTROL
                getter = getattr(k32, "Wow64GetThreadContext", None) or k32.GetThreadContext
                if getter(handle, C.byref(ctx)):
                    eip = ctx.Eip
                    rva = eip - base if base and base <= eip < base + 0x2000000 else None
                    stack_hits = []
                    if args.stack and ctx.Esp:
                        buf = C.create_string_buffer(0x1000)
                        got = C.c_size_t(0)
                        k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p,
                                                          C.c_size_t, C.POINTER(C.c_size_t)]
                        if k32.ReadProcessMemory(proc, C.c_void_p(ctx.Esp & ~0xFFF), buf, 0x1000, C.byref(got)):
                            import struct as _st
                            data = buf.raw[:got.value]
                            for off in range(0, len(data) - 4, 4):
                                val = _st.unpack_from("<I", data, off)[0]
                                if base and base <= val < base + 0x2000000:
                                    stack_hits.append(((ctx.Esp & ~0xFFF) + off, val))
                    rows.append((entry.th32ThreadID, eip, rva, stack_hits[:6]))
                k32.ResumeThread(handle)
                k32.CloseHandle(handle)
        ok = k32.Thread32Next(snapshot, C.byref(entry))
    k32.CloseHandle(snapshot)
    print(f"pid={pid} base={base:#x} threads={len(rows)}")
    wt = window_thread(pid)
    if wt:
        print(f"  window thread: {wt}")
    if args.frames and wt:
        handle = k32.OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, False, wt)
        if handle:
            k32.SuspendThread(handle)
            ctx = CONTEXT(); ctx.ContextFlags = CONTEXT_CONTROL
            getter = getattr(k32, "Wow64GetThreadContext", None) or k32.GetThreadContext
            if getter(handle, C.byref(ctx)):
                import struct as _st
                ebp, esp = ctx.Ebp, ctx.Esp
                print(f"  frame walk: eip={ctx.Eip:#x} esp={esp:#x} ebp={ebp:#x}")
                for depth in range(12):
                    if not ebp:
                        break
                    buf = C.create_string_buffer(8)
                    got = C.c_size_t(0)
                    if not k32.ReadProcessMemory(proc, C.c_void_p(ebp), buf, 8, C.byref(got)) or got.value < 8:
                        print(f"    depth {depth}: unreadable ebp {ebp:#x}")
                        break
                    next_ebp, ret = _st.unpack("<II", buf.raw[:8])
                    inside = base <= ret < base + 0x2000000
                    where = f"file_va {ret - base:#x}" if inside else "outside"
                    print(f"    depth {depth}: ebp={ebp:#x} ret={ret:#x} {where}")
                    if next_ebp <= ebp:
                        break
                    ebp = next_ebp
            k32.ResumeThread(handle)
            k32.CloseHandle(handle)
    for row in rows:
        tid, eip, rva, stack_hits = row
        tag = f"file_va={rva:#x}" if rva is not None else "outside"
        print(f"  tid={tid:<6} eip={eip:#010x} {tag}")
        for addr, val in stack_hits:
            print(f"        stack {addr:#010x} -> file_va {val - base:#x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
