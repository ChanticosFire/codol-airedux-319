"""Send one key press (with optional repeats) to the focused game window.

The native room dialog's combo rows change value with Left/Right when the row
has keyboard focus, which is more reliable than clicking the small arrows.
This wraps SendInput so a row can be focused by a click and then stepped.

    python tools/send_key.py --key right --times 1
    python tools/send_key.py --key return
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = [wt.UINT, ctypes.c_void_p, ctypes.c_int]

KEYEVENTF_KEYUP = 0x0002

KEYS = {
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "return": 0x0D,
    "enter": 0x0D,
    "space": 0x20,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _INPUTunion)]


def press(vk: int) -> None:
    for flags in (0, KEYEVENTF_KEYUP):
        item = INPUT(type=1)
        item.union.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None)
        if user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT)) != 1:
            raise OSError("SendInput failed")
        time.sleep(0.12)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, choices=sorted(KEYS))
    parser.add_argument("--times", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0.35)
    args = parser.parse_args()
    for index in range(args.times):
        press(KEYS[args.key])
        if index + 1 < args.times:
            time.sleep(args.interval)
    print(f"sent {args.key} x{args.times}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
