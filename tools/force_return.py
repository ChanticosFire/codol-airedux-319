"""Force Add to always return at 0xBBA442, then watch whether the status still reaches 3.

The sentinel experiment proved the store at 0xBBA569 never runs even though the count measures 3, which
leaves an unexplained path between 0xBBA442 and the store. This isolates the question from the other
direction: replace the conditional jle with an unconditional jmp to the function epilogue, so Add never
takes either branch into its body. If obj1 status still becomes 3, that write does not come from the
path guarded by this instruction.

    python tools/force_return.py --secs 45

Original at 0xBBA442: 0F 8E 7B 01 00 00   jle 0xBBA5C3
Patched:              E9 7C 01 00 00 90   jmp 0xBBA635 (5 bytes + nop to keep the length)
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
SITE = 0xBBA442
EPILOGUE = 0xBBA635
ORIGINAL = bytes.fromhex("0F8E7B010000")


def build_patch() -> bytes:
    rel = EPILOGUE - (SITE + 5)
    return b"\xE9" + struct.pack("<i", rel) + b"\x90"


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


def write(h, va: int, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(data, len(data))
    wrote = ctypes.c_size_t()
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def u32(h, va: int) -> int | None:
    raw = read(h, va, 4)
    return struct.unpack("<I", raw)[0] if len(raw) == 4 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secs", type=float, default=45.0)
    ap.add_argument("--wait", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=0.05)
    args = ap.parse_args()

    deadline = time.time() + args.wait
    pid = 0
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            break
        time.sleep(0.02)
    if not pid:
        print("client did not appear")
        return 2

    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print("OpenProcess failed")
        return 2
    try:
        wait_img = time.time()
        live = read(h, SITE, len(ORIGINAL))
        while live != ORIGINAL and time.time() - wait_img < 60:
            time.sleep(0.02)
            live = read(h, SITE, len(ORIGINAL))
        if live != ORIGINAL:
            print(f"mismatch at {SITE:#x}: want {ORIGINAL.hex()} got {live.hex()}")
            return 3
        patch = build_patch()
        if not write(h, SITE, patch):
            print("patch failed")
            return 4
        print(f"patched {SITE:#x}: {ORIGINAL.hex()} -> {patch.hex()} "
              f"(jmp {EPILOGUE:#x}, was {time.time() - wait_img:.2f}s)")

        states: list[int] = []
        t0 = time.time()
        while time.time() - t0 < args.secs:
            lobby = u32(h, 0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            status = None
            if lobby:
                obj1 = u32(h, lobby + 0x1F8)
                if obj1:
                    status = u32(h, obj1 + 0x120)
                    if status is not None and (not states or states[-1] != status):
                        states.append(status)
                        print(f"  t={time.time() - t0:6.2f}  status={status}  "
                              f"idx={u32(h, obj1 + 0x130)}  dw={u32(h, 0x84ABA40)}")
            time.sleep(args.interval)

        print(f"\nstatus sequence observed: {states}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
