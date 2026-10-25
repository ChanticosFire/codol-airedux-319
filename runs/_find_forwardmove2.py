"""Continue the plaintext-usercmd hunt in cl+0x4200 .. cl+0x9000.

Round 252 found cl+0x3B94 advancing 1411 -> 1416 while W was held (likely
cmdNumber) but no forwardmove in 0x0..0x4200.  cl->cmds[128] is a few KB, so the
array probably starts past 0x4200.

Same test: a slot that reads 0 while idle and a small nonzero value (typically
+/-127 or 127) while W is held.
"""
import ctypes
import struct
import sys
import time

from ctypes import wintypes as W

pid = int(sys.argv[1])
LO = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x4200
HI = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x9000
XOR = 0x6891D1C7

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


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        return None
    return b.raw


enc = u32(0x76638F4)
cl = (enc ^ XOR) & 0xFFFFFFFF
print("  cl=%#x  state=%s  window=%#x..%#x" % (cl, u32(0x76446B0), LO, HI))

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

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002


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
    inp.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), 0, 0, None)
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


size = HI - LO
idle = rd((cl + LO) & 0xFFFFFFFF, size)
time.sleep(0.3)
key(0x57)
time.sleep(0.35)
held = rd((cl + LO) & 0xFFFFFFFF, size)
time.sleep(0.1)
held2 = rd((cl + LO) & 0xFFFFFFFF, size)
key(0x57, up=True)

if not (idle and held and held2):
    raise SystemExit("read failed")

print()
print("  === 0 while idle, nonzero (and stable) while W held ===")
hits = []
for off in range(0, size - 4, 4):
    a = struct.unpack_from("<i", idle, off)[0]
    b1 = struct.unpack_from("<i", held, off)[0]
    b2 = struct.unpack_from("<i", held2, off)[0]
    if a == 0 and b1 != 0 and b1 == b2 and abs(b1) <= 0x1000:
        hits.append((LO + off, b1))
for off, v in hits[:40]:
    print("    cl+%#06x = %d" % (off, v))
print("  total:", len(hits))

print()
print("  === any change with small magnitudes ===")
chg = []
for off in range(0, size - 4, 4):
    a = struct.unpack_from("<i", idle, off)[0]
    b1 = struct.unpack_from("<i", held, off)[0]
    if a != b1 and abs(a) <= 0x1000 and abs(b1) <= 0x1000:
        chg.append((LO + off, a, b1))
for off, a, b1 in chg[:30]:
    print("    cl+%#06x  %d -> %d" % (off, a, b1))
print("  total changed:", len(chg))
