"""Read the client's plaintext usercmd straight out of memory.

Rationale: the in-band bodies are encrypted, but before encryption the client
builds a plaintext `usercmd_t` (serverTime / buttons / angles / forwardmove /
rightmove / ...) and stores it in `cl->cmds[]`.  So instead of fighting the
cipher we can find `forwardmove` by scanning `cl` while W is held.

Method:
  1. sample a wide window inside `cl` with no keys held
  2. hold W and sample again
  3. report every 4-byte slot whose value changed from 0 to a nonzero small int
     (forwardmove is typically 0 or +/-127)
"""
import ctypes
import struct
import sys
import time

from ctypes import wintypes as W

pid = int(sys.argv[1])
XOR = 0x6891D1C7
SPAN = 0x4200          # cover the whole structure we have been mapping
STEP = 4

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


def s32(a):
    v = u32(a)
    if v is None:
        return None
    return v - 0x100000000 if v >= 0x80000000 else v


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        return None
    return b.raw


enc = u32(0x76638F4)
cl = (enc ^ XOR) & 0xFFFFFFFF
print("  cl = %#x   cls.state = %s" % (cl, u32(0x76446B0)))

# focus the window
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


def sample():
    buf = rd(cl, SPAN)
    if not buf:
        return None
    return buf


print("  sampling idle ...")
idle = sample()
time.sleep(0.4)

print("  holding W and sampling ...")
key(0x57)
time.sleep(0.35)
held = sample()
time.sleep(0.1)
held2 = sample()
key(0x57, up=True)
time.sleep(0.2)

if not (idle and held):
    raise SystemExit("sample failed")

print()
print("  === slots that are 0 when idle but nonzero while W is held ===")
hits = []
for off in range(0, min(len(idle), len(held)) - 4, STEP):
    a = struct.unpack_from("<i", idle, off)[0]
    b1 = struct.unpack_from("<i", held, off)[0]
    b2 = struct.unpack_from("<i", held2, off)[0]
    if a == 0 and b1 != 0 and b1 == b2 and abs(b1) <= 0x400:
        hits.append((off, b1))
for off, v in hits[:40]:
    print("    cl+%#06x = %d" % (off, v))
print("  total:", len(hits))

print()
print("  === slots that changed at all between idle and held (any value) ===")
chg = []
for off in range(0, min(len(idle), len(held)) - 4, STEP):
    a = struct.unpack_from("<i", idle, off)[0]
    b1 = struct.unpack_from("<i", held, off)[0]
    if a != b1 and abs(b1) <= 0x10000 and abs(a) <= 0x10000:
        chg.append((off, a, b1))
for off, a, b1 in chg[:30]:
    print("    cl+%#06x  %d -> %d" % (off, a, b1))
print("  total changed:", len(chg))
