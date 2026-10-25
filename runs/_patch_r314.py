"""Round 100: neutralise the two suspicious reads at 0x515738 / 0x51573E.

Round 99 bracketed the crash between 0x515728 (which sets [0x76446A3]=1, observed
as f3=1) and 0x51575A (which sets [0x76446A2]=1, observed as f2=0), and Round 98
showed 0x453760 is never entered.  So the fault is in one of these:

    0x515735  mov eax, [esi+4]
    0x515738  mov ecx, [esi+0x80150]     <- suspicious
    0x51573E  mov edx, [esi+0x80148]     <- suspicious
    0x515744  push ... x4
    0x515748  mov byte [0x2F9FCDF], 0
    0x51574F  call 0x453760

Replace both loads with `xor ecx,ecx` / `xor edx,edx` (+nop).  This is harmless
(those two values are then passed as 0 to 0x453760) and tells us whether the
crash is really these reads.

Usage: python runs/_patch_r314.py <pid>
"""
import ctypes
import struct
import sys
from ctypes import wintypes as W

PID = int(sys.argv[1])

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualAllocEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD, W.DWORD]
k.VirtualProtectEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                               W.DWORD, ctypes.POINTER(W.DWORD)]
k.VirtualProtectEx.restype = W.BOOL

h = k.OpenProcess(0x1F0FFF, False, PID)
if not h:
    raise SystemExit("OpenProcess failed")


def rd(addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
        return None
    return buf.raw


def u32(addr):
    d = rd(addr, 4)
    return struct.unpack("<I", d)[0] if d else None


def patched_name(addr, n=4):
    d = rd(addr, n)
    return d.hex(" ") if d else "unreadable"


def patch(addr, old, new, label):
    cur = rd(addr, len(old))
    print(f"  {label}")
    print(f"    {addr:#x} expect={old.hex(' ')} actual={cur.hex(' ') if cur else None} "
          f"match={cur == old}")
    prot = W.DWORD()
    k.VirtualProtectEx(h, ctypes.c_void_p(addr), len(new), 0x40, ctypes.byref(prot))
    got = ctypes.c_size_t()
    ok = k.WriteProcessMemory(h, ctypes.c_void_p(addr),
                              ctypes.create_string_buffer(new, len(new)),
                              len(new), ctypes.byref(got))
    k.VirtualProtectEx(h, ctypes.c_void_p(addr), len(new), prot.value, ctypes.byref(prot))
    k.FlushInstructionCache(h, ctypes.c_void_p(addr), len(new))
    after = rd(addr, len(new))
    print(f"    -> {after.hex(' ') if after else None} ok={ok}")
    return ok


print("=== inspect the two loads ===")
print(f"  0x515738: {patched_name(0x515738, 6)}")
print(f"  0x51573E: {patched_name(0x51573E, 6)}")

print()
print("=== patch set ===")
# existing patches (idempotent; they show match=True if unpatched)
patch(0x5C2303, bytes.fromhex("0f8c0a010000"), b"\x90" * 6, "net_state>=7 gate")
patch(0x5C23FF, bytes.fromhex("8d9000feffff"), bytes.fromhex("31d290909090"), "serial window")
patch(0x5C265F, bytes.fromhex("e86cfeffff"), b"\x90" * 5, "NOP timeout handler call")

# NEW: neutralise the two suspicious loads
patch(0x515738, bytes.fromhex("8b8e500108")[:6] if False else bytes.fromhex("8b8e50010800"),
      bytes.fromhex("31c990909090"), "neutralise mov ecx,[esi+0x80150]")
patch(0x51573E, bytes.fromhex("8b9648010800"),
      bytes.fromhex("31d290909090"), "neutralise mov edx,[esi+0x80148]")

# ui_mapname
va = k.VirtualAllocEx(h, None, 256, 0x3000, 0x04)
if va and va < 0x100000000:
    s = b"mp_crash_tropical\x00"
    got = ctypes.c_size_t()
    k.WriteProcessMemory(h, ctypes.c_void_p(va),
                         ctypes.create_string_buffer(s, len(s)), len(s), ctypes.byref(got))
    BASE = 0x80FC008
    patch(BASE + 12, struct.pack("<I", u32(BASE + 12) or 0),
          struct.pack("<I", va), "ui_mapname valptr")

# clear skip flag
FLAG = 0xC7341DB
prot = W.DWORD()
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, 0x40, ctypes.byref(prot))
got = ctypes.c_size_t()
k.WriteProcessMemory(h, ctypes.c_void_p(FLAG), ctypes.create_string_buffer(b"\x00", 1), 1,
                     ctypes.byref(got))
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, prot.value, ctypes.byref(prot))

# arm
enc = u32(0x331C0C8)
conn = (enc ^ 0xD362501F) if enc else 0
if 0x10000 <= conn < 0x7FFF0000:
    adr = struct.pack("<I4sHHIII", 2, b"\0\0\0\0", 0, 0, 0, 0, 0x9D)
    k.WriteProcessMemory(h, ctypes.c_void_p(conn + 0x14),
                         ctypes.create_string_buffer(adr, len(adr)), len(adr),
                         ctypes.byref(got))
    print(f"  conn={conn:#x} adr written")
print(f"  net_state = {u32(0x76446B0)}")
