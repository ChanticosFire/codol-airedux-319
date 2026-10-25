"""Capture the game window in the background with PrintWindow.

front_capture.ps1 copies the screen, so it only works while the game is the
foreground window.  Experiments frequently run while the desktop is in use, so
this helper asks the window to render itself into a bitmap instead
(PW_RENDERFULLCONTENT = 2), which does not steal focus.

    python tools/capture_window_bg.py --out runs/shot.png
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W

from PIL import Image

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
        ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
        ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG),
        ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD),
    ]


def capture(hwnd: int, flags: int = 2) -> Image.Image:
    rect = W.RECT()
    u.GetClientRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise SystemExit("empty client rect")
    hdc = u.GetDC(hwnd)
    memdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, width, height)
    g.SelectObject(memdc, bmp)
    ok = u.PrintWindow(hwnd, memdc, flags)
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32
    buf = ctypes.create_string_buffer(width * height * 4)
    got = g.GetDIBits(memdc, bmp, 0, height, buf, ctypes.byref(header), 0)
    g.DeleteObject(bmp)
    g.DeleteDC(memdc)
    u.ReleaseDC(hwnd, hdc)
    if not ok:
        raise SystemExit("PrintWindow failed")
    if got != height:
        raise SystemExit(f"GetDIBits returned {got} rows")
    return Image.frombuffer("RGBA", (width, height), buf.raw, "raw", "BGRA", 0, 1).convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--class", dest="class_name", default="CODO")
    parser.add_argument("--flags", type=int, default=2)
    args = parser.parse_args()
    u.FindWindowW.restype = W.HWND
    hwnd = u.FindWindowW(args.class_name, None)
    if not hwnd:
        raise SystemExit(f"window class {args.class_name!r} not found")
    image = capture(hwnd, args.flags)
    extrema = image.convert("L").getextrema()
    image.save(args.out)
    print(f"{args.out} {image.width}x{image.height} luma_minmax={extrema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
