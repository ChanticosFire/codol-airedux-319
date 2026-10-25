"""Hold the local playerState at a chosen origin while injecting W.

Round 233/235 established:
  - cl+0x3BA4 is playerState_t (pm_type first field, verified 2 -> 0)
  - origin lives at playerState+0xDC/0xE0/0xE4 = (336, 60, 261)
  - the rest of the struct is almost all zero, so the client has no complete
    player to render or move.

The client re-writes playerState every frame from snapshots, so a single poke is
lost.  This script re-writes the fields every 50 ms for several seconds while
holding W, and records whether the values stick and whether the rendered frame
changes.
"""
import ctypes
import struct
import sys
import time

from ctypes import wintypes as W

pid = int(sys.argv[1])
HOLD_SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
XOR = 0x6891D1C7
PS = 0x3BA4

k = ctypes.WinDLL("kernel32")
k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(0x438, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")

user32 = ctypes.WinDLL("user32", use_last_error=True)


def u32(a):
    b = ctypes.create_string_buffer(4)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, 4, ctypes.byref(g)):
        return None
    return struct.unpack("<I", b.raw)[0]


def f32(a):
    v = u32(a)
    return None if v is None else struct.unpack("<f", struct.pack("<I", v))[0]


def w32(a, v):
    b = struct.pack("<I", v & 0xFFFFFFFF)
    g = ctypes.c_size_t()
    return bool(k.WriteProcessMemory(h, ctypes.c_void_p(a), b, 4, ctypes.byref(g)))


def wf(a, v):
    return w32(a, struct.unpack("<I", struct.pack("<f", v))[0])


enc = u32(0x76638F4)
cl = (enc ^ XOR) & 0xFFFFFFFF
print("  cl=%#x  cls.state=%s" % (cl, u32(0x76446B0)))


def report(tag):
    base = (cl + PS) & 0xFFFFFFFF
    pm = u32(base)
    o = [f32((base + 0xDC) & 0xFFFFFFFF),
         f32((base + 0xE0) & 0xFFFFFFFF),
         f32((base + 0xE4) & 0xFFFFFFFF)]
    fl = u32((base + 4) & 0xFFFFFFFF)
    print("  [%-8s] pm_type=%s pm_flags=%s origin=(%.2f, %.2f, %.2f)"
          % (tag, pm, fl, o[0], o[1], o[2]))
    return tuple(o)


print()
print("  === before (idle) ===")
report("before")

# ---- find the window and focus it ----
hwnds = []


@ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
def _enum(hwnd, lparam):
    p = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    if p.value == pid and user32.IsWindowVisible(hwnd):
        hwnds.append(hwnd)
    return True


user32.EnumWindows(_enum, 0)
if hwnds:
    user32.SetForegroundWindow(hwnds[0])
    print("  focused hwnd=%#x" % hwnds[0])

# ---- key injection ----
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
    inp.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC), 0, 0, None)
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


print()
print("  === hold W + rewrite playerState every 50ms for %.0fs ===" % HOLD_SECONDS)
key(0x57)
base = (cl + PS) & 0xFFFFFFFF
t0 = time.monotonic()
n = 0
last = None
while time.monotonic() - t0 < HOLD_SECONDS:
    # rewrite the fields we know about
    w32((base + 0x00) & 0xFFFFFFFF, 0)          # pm_type = PM_NORMAL
    w32((base + 0x04) & 0xFFFFFFFF, 0)          # pm_flags
    wf((base + 0xDC) & 0xFFFFFFFF, 336.0)
    wf((base + 0xE0) & 0xFFFFFFFF, 60.0)
    wf((base + 0xE4) & 0xFFFFFFFF, 261.0)
    n += 1
    if n % 20 == 0:
        last = report("t+%.1f" % (time.monotonic() - t0))
    time.sleep(0.05)
key(0x57, up=True)

print()
print("  === after ===")
final = report("after")
print()
print("  rewrites issued: %d" % n)
