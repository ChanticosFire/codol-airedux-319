"""Walk the first-run flow that appears on every launch, then open the lobby.

A fresh client has no server-side profile, so it always shows, in order:

    1. character select   -> 确认 (bottom right)
    2. keyboard layout    -> 确认 (bottom right)
    3. welcome / training -> 高手   (veteran, skips the tutorial)
    4. lobby              -> 关闭 on the TextField modal

This clicks those steps with configurable client-area coordinates, waiting
between them so the UI can animate. Steps can be skipped or overridden.

    python tools/lobby_flow.py                    # full flow
    python tools/lobby_flow.py --skip-character   # already past step 1
    python tools/lobby_flow.py --dry-run          # print the plan
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
user32.mouse_event.argtypes = [wt.DWORD, ctypes.c_int, ctypes.c_int, wt.DWORD, ctypes.c_void_p]

SW_RESTORE = 9

# client-area coordinates sampled from the archived 1920x1080 screenshots
STEPS = [
    ("character 确认", 1790, 1011, 9000),
    ("keyboard 确认", 1750, 970, 7000),
    ("training 高手", 1200, 430, 8000),
    ("lobby 关闭", 1405, 621, 6000),
]


def find_window(cls: str) -> int:
    hwnd = user32.FindWindowW(cls, None)
    if not hwnd:
        raise SystemExit(f"no window of class {cls}")
    return hwnd


def click_client(hwnd: int, x: int, y: int) -> None:
    point = wt.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise SystemExit("ClientToScreen failed")
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, None)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--skip-character", action="store_true")
    parser.add_argument("--skip-keyboard", action="store_true")
    parser.add_argument("--skip-training", action="store_true")
    parser.add_argument("--skip-close", action="store_true")
    parser.add_argument("--delay-scale", type=float, default=1.0,
                        help="multiply every wait (slow machines > 1.0)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    skip = {
        "character 确认": args.skip_character,
        "keyboard 确认": args.skip_keyboard,
        "training 高手": args.skip_training,
        "lobby 关闭": args.skip_close,
    }
    plan = [s for s in STEPS if not skip[s[0]]]
    if args.dry_run:
        for name, x, y, wait in plan:
            print(f"{name}: ({x}, {y}) wait {wait} ms")
        return 0

    hwnd = find_window(args.window)
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    print(f"client area {rect.right}x{rect.bottom}")
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(2.0)

    for name, x, y, wait in plan:
        wait *= args.delay_scale
        print(f"{name}: waiting {wait/1000:.1f}s", flush=True)
        time.sleep(wait / 1000.0)
        click_client(hwnd, x, y)
        print(f"{name}: clicked ({x}, {y})", flush=True)
        time.sleep(0.8)
    print("flow done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
