"""Activate the game window, send SPACE, then hold W, sampling clc as we go.

Round 227 showed pm_type is now PM_NORMAL (0) and the HUD says "press space",
but injected keys did nothing -- most likely the window had no keyboard focus.
This script brings the window to the foreground first, then drives input and
watches a wide window of clc floats to find the real vieworg.
"""
import ctypes
import struct
import sys
import time
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")

pid = int(sys.argv[1])
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0
XOR = 0x6891D1C7

kernel32.OpenProcess.restype = W.HANDLE
h = kernel32.OpenProcess(0x438, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")

# --- find the game window ---
hwnds = []


@ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
def _enum(hwnd, lparam):
    p = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    if p.value == pid and user32.IsWindowVisible(hwnd):
        hwnds.append(hwnd)
    return True


user32.EnumWindows(_enum, 0)
if not hwnds:
    raise SystemExit("no visible window for pid")
hwnd = hwnds[0]
print("  hwnd=%#x" % hwnd)

# --- activate ---
user32.ShowWindow(hwnd, 9)          # SW_RESTORE
user32.SetForegroundWindow(hwnd)
user32.BringWindowToTop(hwnd)
time.sleep(0.6)
fg = user32.GetForegroundWindow()
print("  foreground now = %#x  (match=%s)" % (fg, fg == hwnd))


def u32(a):
    b = ctypes.create_string_buffer(4)
    g = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(h, ctypes.c_void_p(a), b, 4, ctypes.byref(g)):
        return None
    return struct.unpack("<I", b.raw)[0]


def f32(a):
    v = u32(a)
    return None if v is None else struct.unpack("<f", struct.pack("<I", v))[0]


def sample(tag):
    enc = u32(0x76638F4)
    if not enc:
        return None
    clc = (enc ^ XOR) & 0xFFFFFFFF
    net = u32(0x76446B0)
    vals = [f32((clc + off) & 0xFFFFFFFF) for off in (0x3C80, 0x3C84, 0x3C88)]
    pm = u32((clc + 0x3BA4) & 0xFFFFFFFF)
    print("  [%-10s] net=%-3s pm_type=%-3s pos=(%.2f, %.2f, %.2f)"
          % (tag, net, pm, vals[0], vals[1], vals[2]))
    return tuple(vals)


# --- key injection via SendInput-style scan codes ---
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ctypes.POINTER(W.ULONG))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _U)]


def key(vk, up=False):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC),
                        0, 0, None)
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


print()
print("  === phase 1: idle ===")
before = [sample("idle%d" % i) for i in range(3)]

print()
print("  === phase 2: SPACE ===")
key(0x20)
time.sleep(0.08)
key(0x20, up=True)
time.sleep(1.2)
after_space = [sample("space%d" % i) for i in range(2)]

print()
print("  === phase 3: hold W 1.5s ===")
key(0x57)
t0 = time.monotonic()
held = []
while time.monotonic() - t0 < 1.5:
    held.append(sample("W"))
    time.sleep(0.3)
key(0x57, up=True)
time.sleep(0.6)
after_w = [sample("afterW%d" % i) for i in range(2)]

print()
print("  === summary ===")
allsamp = [s for s in before + after_space + held + after_w if s]
print("  distinct positions seen: %d" % len(set(allsamp)))
for s in sorted(set(allsamp)):
    print("    %.2f, %.2f, %.2f" % s)
