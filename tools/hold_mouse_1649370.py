"""Hold a real mouse button inside the game window (no memory writes).

`hold_key_1649370.py` covers the keyboard; shooting needs the mouse, and the
client only sees input that comes through the normal Windows path.  This uses
`mouse_event`, so it produces genuine WM_*BUTTONDOWN/UP messages and whatever
raw-input layer the client listens on.

    python tools/hold_mouse_1649370.py --button left --ms 1500
    python tools/hold_mouse_1649370.py --button right --ms 500
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]

DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="CODO")
    ap.add_argument("--button", choices=("left", "right", "middle"), default="left")
    ap.add_argument("--ms", type=int, default=1200)
    ap.add_argument("--x", type=int, default=None, help="client-area x for the cursor")
    ap.add_argument("--y", type=int, default=None, help="client-area y for the cursor")
    args = ap.parse_args()

    hwnd = user32.FindWindowW(args.window, None)
    if not hwnd:
        raise SystemExit(f"window {args.window!r} not found")
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    focus_before = user32.GetForegroundWindow()

    if args.x is not None and args.y is not None:
        user32.SetCursorPos(rect.left + args.x, rect.top + args.y)
        time.sleep(0.1)

    payload = json.dumps({"hwnd": hex(hwnd), "button": args.button, "ms": args.ms,
                          "client": [rect.right - rect.left, rect.bottom - rect.top],
                          "foreground_matches": focus_before == hwnd})
    print(payload, flush=True)

    user32.mouse_event(DOWN[args.button], 0, 0, 0, 0)
    time.sleep(max(0.05, args.ms / 1000.0))
    user32.mouse_event(UP[args.button], 0, 0, 0, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
