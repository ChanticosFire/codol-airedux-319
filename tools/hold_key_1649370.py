"""Hold a real key on the CODOL window for a measured duration.

The keyboard path is the only one that can prove the player moves: the client
has to turn the key into a usercmd itself.  This script only presses and
releases; it never touches client memory.

    python runs/_hold_key.py --vk 0x57 --ms 1500
    python runs/_hold_key.py --button right --ms 600
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from ctypes import wintypes as W

user32 = C.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.ShowWindow.argtypes = [W.HWND, C.c_int]
user32.GetForegroundWindow.restype = W.HWND
user32.keybd_event.argtypes = [W.BYTE, W.BYTE, W.DWORD, C.c_size_t]
user32.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
user32.SetCursorPos.argtypes = [C.c_int, C.c_int]

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
SW_RESTORE = 9


class RECT(C.Structure):
    _fields_ = [("left", C.c_long), ("top", C.c_long),
                ("right", C.c_long), ("bottom", C.c_long)]


class POINT(C.Structure):
    _fields_ = [("x", C.c_long), ("y", C.c_long)]


def find_window(window_class: str, title: str) -> int:
    handle = user32.FindWindowW(window_class, title or None)
    if not handle:
        raise SystemExit(f"window not found: class={window_class!r} title={title!r}")
    return handle


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--class", dest="window_class", default="CODO")
    ap.add_argument("--title", default="")
    ap.add_argument("--vk", type=lambda v: int(v, 0), help="virtual key code, e.g. 0x57 for W")
    ap.add_argument("--button", choices=("left", "right"), help="mouse button instead of a key")
    ap.add_argument("--ms", type=int, default=1000)
    args = ap.parse_args()
    if (args.vk is None) == (args.button is None):
        raise SystemExit("give exactly one of --vk / --button")

    handle = find_window(args.window_class, args.title)
    info = {"hwnd": hex(handle), "class": args.window_class, "ms": args.ms}
    user32.ShowWindow(handle, SW_RESTORE)
    user32.SetForegroundWindow(handle)
    time.sleep(0.4)
    rect = RECT()
    user32.GetClientRect(handle, C.byref(rect))
    info["client"] = [rect.right - rect.left, rect.bottom - rect.top]
    info["foreground_matches"] = user32.GetForegroundWindow() == handle
    focus = user32.GetForegroundWindow()

    if args.button is not None:
        origin = POINT(0, 0)
        user32.ClientToScreen(handle, C.byref(origin))
        centre = (origin.x + (rect.right - rect.left) // 2,
                  origin.y + (rect.bottom - rect.top) // 2)
        down = MOUSEEVENTF_LEFTDOWN if args.button == "left" else MOUSEEVENTF_RIGHTDOWN
        up = MOUSEEVENTF_LEFTUP if args.button == "left" else MOUSEEVENTF_RIGHTUP
        user32.SetCursorPos(centre[0], centre[1])
        time.sleep(0.1)
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(args.ms / 1000.0)
        user32.mouse_event(up, 0, 0, 0, 0)
        info["action"] = args.button
        info["cursor"] = list(centre)
    else:
        user32.keybd_event(args.vk, 0, 0, 0)
        time.sleep(args.ms / 1000.0)
        user32.keybd_event(args.vk, 0, KEYEVENTF_KEYUP, 0)
        info["action"] = f"vk=0x{args.vk:02x}"

    info["focus_before"] = hex(focus) if focus else "0x0"
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
