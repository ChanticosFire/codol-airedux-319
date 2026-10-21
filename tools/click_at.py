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
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]

SW_RESTORE = 9
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def move_absolute(x: int, y: int) -> None:
    """Move through the input queue so the game receives WM_MOUSEMOVE.

    SetCursorPos alone only changes the system cursor; a Scaleform window that
    tracks hover from mouse messages can still believe the pointer is at its
    previous location and route the following click to stale hit-test data.
    """
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    nx = int(round(x * 65535 / max(1, width - 1)))
    ny = int(round(y * 65535 / max(1, height - 1)))
    user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny, 0, None)


def click(x: int, y: int) -> None:
    move_absolute(x, y)
    time.sleep(0.35)
    # left down + left up via mouse_event
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.12)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)


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
    parser.add_argument("--method", choices=("mouse", "post"), default="mouse",
                        help="synthesized mouse input, or WM_MOUSE* messages to the window")
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
    if args.method == "post":
        x, y = args.at
        lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        user32.PostMessageW(hwnd, 0x0200, 0, lparam)          # WM_MOUSEMOVE
        time.sleep(0.2)
        user32.PostMessageW(hwnd, 0x0201, 1, lparam)          # WM_LBUTTONDOWN
        time.sleep(0.12)
        user32.PostMessageW(hwnd, 0x0202, 0, lparam)          # WM_LBUTTONUP
        print(f"posted click at client {args.at}")
        return 0
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
