"""Click inside the CODOL window using physical cursor events.

The lobby UI is fully rendered once ui_state == 0, so the native path to a
match is the same one a player takes: click the navigation tabs.

Coordinates are given in the reference frame of a 1920x1080 capture and are
scaled to the live client rect, so screenshots taken with capture_window.ps1
can be used directly.

    python tools/click_1649370.py --x 430 --y 57
    python tools/click_1649370.py --x 430 --y 57 --double
    python tools/click_1649370.py --probe          # print geometry only
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from ctypes import wintypes as W

user32 = C.WinDLL("user32", use_last_error=True)
k32 = C.WinDLL("kernel32", use_last_error=True)

REF_W, REF_H = 1920.0, 1080.0

user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.ShowWindow.argtypes = [W.HWND, C.c_int]
user32.SetCursorPos.argtypes = [C.c_int, C.c_int]
user32.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
SW_RESTORE = 9


def geometry(hwnd: W.HWND) -> dict:
    rect = W.RECT()
    if not user32.GetClientRect(hwnd, C.byref(rect)):
        raise SystemExit(f"GetClientRect failed err={C.get_last_error()}")
    origin = W.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, C.byref(origin)):
        raise SystemExit(f"ClientToScreen failed err={C.get_last_error()}")
    return {"client_w": rect.right - rect.left, "client_h": rect.bottom - rect.top,
            "screen_x": origin.x, "screen_y": origin.y}


def click(hwnd: W.HWND, ref_x: float, ref_y: float, double: bool, settle: float) -> dict:
    geo = geometry(hwnd)
    if geo["client_w"] <= 0 or geo["client_h"] <= 0:
        raise SystemExit("client rect is empty")
    sx = geo["screen_x"] + int(round(ref_x * geo["client_w"] / REF_W))
    sy = geo["screen_y"] + int(round(ref_y * geo["client_h"] / REF_H))
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    user32.SetCursorPos(sx, sy)
    time.sleep(0.12)
    clicks = 2 if double else 1
    for _ in range(clicks):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.10)
    time.sleep(settle)
    return {"hwnd": hex(hwnd), "ref": [ref_x, ref_y], "screen": [sx, sy],
            "clicks": clicks, **geo}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", type=float, default=0.0)
    ap.add_argument("--y", type=float, default=0.0)
    ap.add_argument("--window", default="CODO")
    ap.add_argument("--double", action="store_true")
    ap.add_argument("--settle", type=float, default=1.2)
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    hwnd = user32.FindWindowW(args.window, None)
    if not hwnd:
        raise SystemExit(f"window class {args.window!r} not found")
    if args.probe:
        print(json.dumps({"hwnd": hex(hwnd), **geometry(hwnd)}, indent=2))
        return 0
    print(json.dumps(click(hwnd, args.x, args.y, args.double, args.settle), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
