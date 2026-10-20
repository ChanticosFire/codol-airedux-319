"""Type text into the game window via SendInput, optionally clicking first.

The first-run flow ends at a "取一个代号" prompt with a text field. This clicks
the field, types a name, and can then click 继续.

    python tools/type_text.py --click 980 610 --text "Player" --enter
    python tools/type_text.py --text "Player"        # type into current focus

Unicode is sent as WM_CHAR to the focused control so Chinese names work too;
ASCII goes through SendInput like a real keyboard.
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
user32.mouse_event.argtypes = [wt.DWORD, ctypes.c_int, ctypes.c_int, wt.DWORD, ctypes.c_void_p]
user32.GetForegroundWindow.restype = wt.HWND

SW_RESTORE = 9
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTunion)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetFocus.restype = wt.HWND
user32.GetForegroundWindow.restype = wt.HWND
WM_CHAR = 0x0102


def click_screen(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, None)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, None)


def send_unicode_char(ch: str) -> None:
    code = ord(ch)
    down = INPUT(type=1, u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
    up = INPUT(type=1, u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(0.02)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
    time.sleep(0.02)


def post_char(hwnd: int, ch: str) -> None:
    """Send WM_CHAR to the window; Scaleform listens for this, not SendInput."""
    user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 1)


def send_vk(vk: int) -> None:
    down = INPUT(type=1, u=_INPUTunion(ki=KEYBDINPUT(vk, 0, 0, 0, None)))
    up = INPUT(type=1, u=_INPUTunion(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, None)))
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(0.05)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--text", default="")
    parser.add_argument("--click", nargs=2, type=int, metavar=("X", "Y"),
                        help="client-area coordinates to click before typing")
    parser.add_argument("--enter", action="store_true", help="press Enter afterwards")
    parser.add_argument("--activate-at", nargs=2, type=int, metavar=("X", "Y"),
                        default=[860, 300],
                        help="neutral client-area point clicked first to give the window focus")
    parser.add_argument("--no-activate", dest="activate", action="store_false", default=True,
                        help="skip the activation click")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--method", choices=["sendinput", "wmchar"], default="wmchar",
                        help="wmchar posts WM_CHAR (works for Scaleform); sendinput is best-effort")
    args = parser.parse_args()

    hwnd = user32.FindWindowW(args.window, None)
    if not hwnd:
        print(f"no window of class {args.window}", file=sys.stderr)
        return 2
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(args.delay)

    def click_client(cx: int, cy: int, label: str) -> None:
        point = wt.POINT(cx, cy)
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            print("ClientToScreen failed", file=sys.stderr)
            return
        print(f"{label}: clicking screen ({point.x}, {point.y})")
        click_screen(point.x, point.y)

    if args.activate:
        # Scaleform only accepts text once the window has real focus; clicking a
        # neutral spot first is what a human does before clicking the field.
        click_client(args.activate_at[0], args.activate_at[1], "activate")
        time.sleep(0.8)

    if args.click:
        point = wt.POINT(args.click[0], args.click[1])
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            print("ClientToScreen failed", file=sys.stderr)
            return 3
        print(f"clicking screen ({point.x}, {point.y})")
        click_screen(point.x, point.y)
        time.sleep(0.6)

    if args.text:
        method = args.method
        print(f"typing {args.text!r} via {method}")
        for ch in args.text:
            if method == "wmchar":
                post_char(hwnd, ch)
            else:
                send_unicode_char(ch)
            time.sleep(0.05)
    if args.enter:
        time.sleep(0.3)
        send_vk(0x0D)  # VK_RETURN
        print("pressed Enter")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
