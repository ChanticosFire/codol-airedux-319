"""Walk the main thread stack and keep only entries that look like real return addresses.

Scanning dwords on the stack is unreliable (section 800): most slots hold data.
A dword is a credible return address only if the instruction immediately before
it is a call (E8 rel32, FF /2, FF /3) or, for a call with a prefix, one of the
common short forms.  This tool validates each candidate by disassembling
backwards a few bytes at candidate-5 / candidate-2 / candidate-6 and reporting
which pattern matched.

    python tools/stack_walk_1649370.py --pid 1234 --tid 5678
    python tools/stack_walk_1649370.py --pid 1234 --all
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


class CTX(ctypes.Structure):
    _fields_ = [
        ("ContextFlags", W.DWORD), ("Dr0", W.DWORD), ("Dr1", W.DWORD), ("Dr2", W.DWORD),
        ("Dr3", W.DWORD), ("Dr6", W.DWORD), ("Dr7", W.DWORD),
        ("FloatSave", ctypes.c_byte * 112),
        ("SegGs", W.DWORD), ("SegFs", W.DWORD), ("SegEs", W.DWORD), ("SegDs", W.DWORD),
        ("Edi", W.DWORD), ("Esi", W.DWORD), ("Ebx", W.DWORD), ("Edx", W.DWORD),
        ("Ecx", W.DWORD), ("Eax", W.DWORD), ("Ebp", W.DWORD), ("Eip", W.DWORD),
        ("SegCs", W.DWORD), ("EFlags", W.DWORD), ("Esp", W.DWORD), ("SegSs", W.DWORD),
        ("ExtendedRegisters", ctypes.c_byte * 512),
    ]


class TE(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ThreadID", W.DWORD),
                ("th32OwnerProcessID", W.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", W.DWORD)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--tid", type=int)
    ap.add_argument("--all", action="store_true", help="walk every thread")
    ap.add_argument("--depth", type=lambda v: int(v, 0), default=0x100)
    args = ap.parse_args()

    h = k32.OpenProcess(0x438, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    def rd(va: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, size, ctypes.byref(n))
        return buf.raw if ok and n.value == size else None

    tids = []
    if args.all or args.tid is None:
        k32.CreateToolhelp32Snapshot.restype = W.HANDLE
        snap = k32.CreateToolhelp32Snapshot(0x4, 0)
        te = TE()
        te.dwSize = ctypes.sizeof(te)
        if k32.Thread32First(snap, ctypes.byref(te)):
            while True:
                if te.th32OwnerProcessID == args.pid:
                    tids.append(te.th32ThreadID)
                if not k32.Thread32Next(snap, ctypes.byref(te)):
                    break
        k32.CloseHandle(snap)
    else:
        tids = [args.tid]

    for tid in tids:
        th = k32.OpenThread(0x1F03FF, False, tid)
        if not th:
            continue
        k32.SuspendThread(th)
        c = CTX()
        c.ContextFlags = 0x1003F
        ok = k32.Wow64GetThreadContext(th, ctypes.byref(c))
        k32.ResumeThread(th)
        k32.CloseHandle(th)
        if not ok:
            continue
        print(f"tid={tid} eip={c.Eip:#010x} esp={c.Esp:#010x} ebp={c.Ebp:#010x}")
        raw = rd(c.Esp, args.depth)
        if not raw:
            continue
        for i in range(0, args.depth - 4, 4):
            v = struct.unpack_from("<I", raw, i)[0]
            if not (0x401000 <= v < 0xEA5C000):
                continue
            note = ""
            for back, label in ((5, "call rel32"), (2, "call r/m (2b)"), (6, "call r/m (6b)")):
                pre = rd(v - back, back)
                if not pre:
                    continue
                if back == 5 and pre[0] == 0xE8:
                    note = label
                    break
                if back == 2 and len(pre) == 2 and pre[0] == 0xFF and (pre[1] & 0x38) == 0x10:
                    note = label
                    break
                if back == 6 and len(pre) == 6 and pre[0] == 0xFF and (pre[1] & 0x38) == 0x10:
                    note = label
                    break
            if note:
                print(f"   [esp+{i:#04x}] {v:#010x}  <- {note}")
        print()
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
