"""Scan candidate playerState fields for the camera view height.

The camera sits on the floor, so some field that should be 60 (standing eye
height) reads 0.  For every zero 4-byte slot in a window of clientActive_t this
writes 60, captures the game window through PrintWindow (no focus stealing) and
measures how much the frame changed.  A slot that raises the camera produces a
large frame delta; slots that do nothing are restored immediately.

    python tools/scan_viewheight_1649370.py --pid 24852 --from 0x0 --to 0x200
"""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_window_bg import capture  # noqa: E402

CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
VALUE = 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--from", dest="start", type=lambda t: int(t, 0), default=0)
    parser.add_argument("--to", dest="end", type=lambda t: int(t, 0), default=0x200)
    parser.add_argument("--out-dir", type=Path, default=Path("runs/viewheight-scan"))
    parser.add_argument("--threshold", type=float, default=2.0)
    args = parser.parse_args()

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = W.HANDLE
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    h = k.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit("OpenProcess failed")
    got = ctypes.c_size_t()

    def read(addr, size):
        buf = ctypes.create_string_buffer(size)
        if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        return buf.raw

    def write(addr, data):
        old = ctypes.c_ulong()
        k.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), 0x40, ctypes.byref(old))
        ok = k.WriteProcessMemory(h, ctypes.c_void_p(addr), ctypes.create_string_buffer(data),
                                  len(data), ctypes.byref(got))
        k.VirtualProtectEx(h, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(old))
        return bool(ok)

    cl = (struct.unpack("<I", read(CL_PTR, 4))[0]) ^ CL_XOR
    print(f"cl={cl:#x}", flush=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    base = capture(u_hwnd(), 2)
    base.save(args.out_dir / "base.png")
    print("base captured", flush=True)

    rows = []
    for off in range(args.start, args.end, 4):
        addr = cl + off
        word = read(addr, 4)
        if word is None or struct.unpack("<i", word)[0] != 0:
            continue
        if not write(addr, struct.pack("<i", VALUE)):
            continue
        time.sleep(0.25)
        try:
            shot = capture(u_hwnd(), 2)
        except SystemExit:
            write(addr, word)
            continue
        diff = ImageChops.difference(base.convert("L"), shot.convert("L"))
        delta = ImageStat.Stat(diff).mean[0]
        rows.append((off, delta, shot))
        write(addr, word)  # restore
        time.sleep(0.05)
        if delta >= args.threshold:
            path = args.out_dir / f"cl_{off:#06x}.png"
            shot.save(path)
            print(f"cl+{off:#06x} delta={delta:.2f} SAVED {path}", flush=True)
        else:
            print(f"cl+{off:#06x} delta={delta:.2f}", flush=True)

    rows.sort(key=lambda row: -row[1])
    print("top deltas:", [(hex(off), round(delta, 2)) for off, delta, _ in rows[:10]])
    return 0


def u_hwnd():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.FindWindowW.restype = W.HWND
    return u.FindWindowW("CODO", None)


if __name__ == "__main__":
    raise SystemExit(main())
