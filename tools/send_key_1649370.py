"""Send real keyboard input to the CODOL window.

`closemenu` does nothing on the demo result screen and PowerShell's
`FindWindowW` returned 0 when passed `$null`, so drive the window the way a
player would: focus it, then emit key down/up pairs.

    python tools/send_key_1649370.py --key esc
    python tools/send_key_1649370.py --key esc --settle 2
    python tools/send_key_1649370.py --vk 0x1B --repeat 2
    python tools/send_key_1649370.py --probe
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
user32.keybd_event.argtypes = [W.BYTE, W.BYTE, W.DWORD, C.c_size_t]
user32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]

KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9

NAMED = {
    "esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "space": 0x20,
    "backspace": 0x08, "tab": 0x09,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="CODO")
    ap.add_argument("--key", default="esc")
    ap.add_argument("--vk", type=lambda v: int(v, 0), default=None)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.15)
    ap.add_argument("--settle", type=float, default=1.5)
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    hwnd = user32.FindWindowW(args.window, None)
    if not hwnd:
        raise SystemExit(f"window class {args.window!r} not found")
    rect = W.RECT()
    user32.GetClientRect(hwnd, C.byref(rect))
    info = {"hwnd": hex(hwnd), "client_w": rect.right - rect.left,
            "client_h": rect.bottom - rect.top}
    if args.probe:
        print(json.dumps(info, indent=2))
        return 0

    vk = args.vk if args.vk is not None else NAMED.get(args.key.lower())
    if vk is None:
        raise SystemExit(f"unknown key {args.key!r}; use --vk or one of {sorted(NAMED)}")

    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    for _ in range(args.repeat):
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(args.gap)
    time.sleep(args.settle)
    info.update(vk=hex(vk), repeat=args.repeat, sent=True)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
