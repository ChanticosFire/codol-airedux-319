"""Click a point inside the game window (or bring it forward first).

The lobby's TextField modal has a 关闭 button; this clicks it so the lobby
becomes interactive. Coordinates are given in the window's client area by
default, so a moved or resized window still works.

Examples:
    python tools/click_at.py --window CODO --at 1405 621
    python tools/click_at.py --window CODO --at 300 400 --title "多人游戏"
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

user32.FindWindowW.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

SW_RESTORE = 9


def click(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    # left down + left up via mouse_event
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", default="CODO", help="window class name")
    parser.add_argument("--at", nargs=2, type=int, metavar=("X", "Y"),
                        required=True, help="client-area coordinates")
    parser.add_argument("--foreground", action="store_true", default=True,
                        help="bring the window forward first (default)")
    parser.add_argument("--no-foreground", dest="foreground", action="store_false")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds to wait after bringing the window forward")
    args = parser.parse_args()

    hwnd = user32.FindWindowW(args.window, None)
    if not hwnd:
        print(f"no window of class {args.window}", file=sys.stderr)
        return 2
    rect = wt.RECT()
    if user32.GetClientRect(hwnd, ctypes.byref(rect)):
        print(f"client area {rect.right}x{rect.bottom}")
    if args.foreground:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(args.delay)
    point = wt.POINT(args.at[0], args.at[1])
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        print("ClientToScreen failed", ctypes.get_last_error(), file=sys.stderr)
        return 3
    print(f"clicking screen ({point.x}, {point.y}) from client {args.at}")
    click(point.x, point.y)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
