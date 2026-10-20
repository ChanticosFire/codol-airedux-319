"""Sample thread contexts to catch the pump inside 0xBAD800 and read its locals.

Several rounds have asked what the 1288-byte container record should contain while
0xBBAD40 only copies 136 bytes. The source buffer is the local at [ebp-0x658] in
pump (see 0xBAE72D), so this polls every thread's Eip and, whenever one is inside
the pump or 0xBBAD40, dumps the frame's locals.

    python tools/catch_pump_frame.py 20
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
THREAD_ALL = 0x1F03FF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenThread.restype = wt.HANDLE
k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]


class CONTEXT(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", wt.DWORD),
        ("Dr0", wt.DWORD), ("Dr1", wt.DWORD), ("Dr2", wt.DWORD), ("Dr3", wt.DWORD),
        ("Dr6", wt.DWORD), ("Dr7", wt.DWORD),
        ("FloatSave", ctypes.c_byte * 112),
        ("SegGs", wt.DWORD), ("SegFs", wt.DWORD), ("SegEs", wt.DWORD), ("SegDs", wt.DWORD),
        ("Edi", wt.DWORD), ("Esi", wt.DWORD), ("Ebx", wt.DWORD), ("Edx", wt.DWORD),
        ("Ecx", wt.DWORD), ("Eax", wt.DWORD),
        ("Ebp", wt.DWORD), ("Eip", wt.DWORD), ("SegCs", wt.DWORD), ("EFlags", wt.DWORD),
        ("Esp", wt.DWORD), ("SegSs", wt.DWORD),
    ]


k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.POINTER(CONTEXT)]
CONTEXT_FULL = 0x00010007
PUMP_LO, PUMP_HI = 0xBAD800, 0xBAE900
BAD40_LO, BAD40_HI = 0xBBAD40, 0xBBADE0
EXE = "codomp_client_shipretail.exe"


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def read(h, va: int, n: int) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
    return buf.raw[:got.value] if ok else b""


def thread_ids(pid: int) -> list[int]:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    # tasklist does not list threads; use the toolhelp snapshot instead
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    ids: list[int] = []
    if snap and snap != wt.HANDLE(-1).value:

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                        ("th32ThreadID", wt.DWORD), ("th32OwnerProcessID", wt.DWORD),
                        ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                        ("dwFlags", wt.DWORD)]

        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        k32.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
        k32.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
        ok = k32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                ids.append(entry.th32ThreadID)
            ok = k32.Thread32Next(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)
    return ids


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    pid = find_pid()
    if not pid:
        print("client not running")
        return 2
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 3
    tids = thread_ids(pid)
    print(f"pid={pid} threads={len(tids)} watching {secs:g}s")
    hits = 0
    deadline = time.time() + secs
    seen: set[str] = set()
    try:
        while time.time() < deadline:
            for tid in tids:
                th = k32.OpenThread(THREAD_ALL, False, tid)
                if not th:
                    continue
                try:
                    ctx = CONTEXT()
                    ctx.ContextFlags = CONTEXT_FULL
                    if not k32.GetThreadContext(th, ctypes.byref(ctx)):
                        continue
                    eip = ctx.Eip
                    if PUMP_LO <= eip < PUMP_HI or BAD40_LO <= eip < BAD40_HI:
                        key = f"{eip:#x}"
                        if key in seen:
                            continue
                        seen.add(key)
                        hits += 1
                        region = "pump" if PUMP_LO <= eip < PUMP_HI else "0xBBAD40"
                        print(f"hit {region} eip={eip:#x} ebp={ctx.Ebp:#x} esp={ctx.Esp:#x}")
                        if region == "pump":
                            src = ctx.Ebp - 0x658
                            blob = read(h, src, 160)
                            if blob:
                                print(f"  [ebp-0x658] = {src:#x}, first 144B:")
                                for off in range(0, min(len(blob), 144), 16):
                                    ch = blob[off:off + 16]
                                    hx = " ".join(f"{b:02x}" for b in ch)
                                    tx = "".join(chr(b) if 32 <= b < 127 else "." for b in ch)
                                    print(f"    {src + off:#010x}  {hx:<48} {tx}")
                        if hits >= 3:
                            return 0
                finally:
                    k32.CloseHandle(th)
            time.sleep(0.002)
    finally:
        k32.CloseHandle(h)
    print(f"done, {hits} distinct hit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
