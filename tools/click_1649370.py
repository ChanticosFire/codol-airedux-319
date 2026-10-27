"""Click inside the CODOL window at client-relative coordinates.

    python tools/click_1649370.py --x 680 --y 57
    python tools/click_1649370.py --x 960 --y 620 --double
"""
from __future__ import annotations

import argparse
import ctypes
import time
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
user32.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, ctypes.c_size_t]
user32.ClientToScreen.restype = W.BOOL

SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", default="CODO")
    ap.add_argument("--x", type=int, required=True)
    ap.add_argument("--y", type=int, required=True)
    ap.add_argument("--double", action="store_true")
    ap.add_argument("--settle", type=float, default=1.2)
    args = ap.parse_args()
    hwnd = user32.FindWindowW(args.window, None)
    if not hwnd:
        raise SystemExit(f"window class {args.window!r} not found")
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    point = W.POINT(args.x, args.y)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.15)
    for _ in range(2 if args.double else 1):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.12)
    time.sleep(args.settle)
    print(f"clicked ({args.x},{args.y}) -> screen ({point.x},{point.y}) hwnd={hex(hwnd)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
