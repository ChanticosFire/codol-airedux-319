"""Round 93: cut the ONLY call to the timeout handler 0x5C24D0.

Round 92 established:
  * 0x5C24D0 always reports EXE_ERR_SERVER_TIMEOUT (both the `jl` path and the
    fall-through path end at the same push/Com_Error),
  * its only caller is 0x5C265F,
  * upstream there are two timeout conditions (retry counter [conn+0x34] >
    [[0x33D64A0]+0xC], and a floating-point elapsed-time compare).

So NOP the call itself: `E8 xx xx xx xx` -> `90 90 90 90 90`.  A call does not
change ESP (the callee's `add esp,8` happens inside the callee), so removing it
leaves the stack balanced.

Usage: python runs/_patch_r308.py <pid>
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


def u8(addr):
    d = rd(addr, 1)
    return d[0] if d else None


def cstr(addr, n=48):
    if not addr:
        return None
    d = rd(addr, n)
    if not d:
        return None
    z = d.find(b"\x00")
    return d[:z] if z >= 0 else d


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


# --- show what we are about to cut -------------------------------------------
raw = rd(0x5C265F, 5)
print(f"  bytes at 0x5C265F (call 0x5C24D0): {raw.hex(' ') if raw else None}")
if raw and raw[0] == 0xE8:
    rel = struct.unpack_from("<i", raw, 1)[0]
    dest = (0x5C265F + 5 + rel) & 0xFFFFFFFF
    print(f"    decoded target = {dest:#x}  (expected 0x5C24D0)")
else:
    print("    [WARN] not an E8 call — will still attempt the NOP patch below")

# --- patch set ---------------------------------------------------------------
va = k.VirtualAllocEx(h, None, 256, 0x3000, 0x04)
if va and va < 0x100000000:
    s = b"mp_crash_tropical\x00"
    got = ctypes.c_size_t()
    k.WriteProcessMemory(h, ctypes.c_void_p(va),
                         ctypes.create_string_buffer(s, len(s)), len(s), ctypes.byref(got))
    BASE = 0x80FC008
    patch(BASE + 12, struct.pack("<I", u32(BASE + 12) or 0),
          struct.pack("<I", va), "ui_mapname valptr")
    print(f"    value now = {cstr(u32(BASE + 12))}")

patch(0x5C2303, bytes.fromhex("0f8c0a010000"), b"\x90" * 6, "net_state>=7 gate")
patch(0x5C23FF, bytes.fromhex("8d9000feffff"), bytes.fromhex("31d290909090"), "serial window")
patch(0x5C2530, bytes.fromhex("7c57"), bytes.fromhex("9090"), "jl at 0x5C2530 (harmless now)")

# THE KEY PATCH
patch(0x5C265F, bytes.fromhex("e86cfeffff"), b"\x90" * 5,
      "NOP the call to the timeout handler (0x5C265F)")

# clear skip flag + arm
FLAG = 0xC7341DB
prot = W.DWORD()
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, 0x40, ctypes.byref(prot))
got = ctypes.c_size_t()
k.WriteProcessMemory(h, ctypes.c_void_p(FLAG), ctypes.create_string_buffer(b"\x00", 1), 1,
                     ctypes.byref(got))
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, prot.value, ctypes.byref(prot))
print(f"  [0xC7341DB] = {u8(FLAG)}")

enc = u32(0x331C0C8)
conn = (enc ^ 0xD362501F) if enc else 0
if 0x10000 <= conn < 0x7FFF0000:
    adr = struct.pack("<I4sHHIII", 2, b"\0\0\0\0", 0, 0, 0, 0, 0x9D)
    k.WriteProcessMemory(h, ctypes.c_void_p(conn + 0x14),
                         ctypes.create_string_buffer(adr, len(adr)), len(adr),
                         ctypes.byref(got))
    print(f"  conn={conn:#x} adr written")
print(f"  net_state = {u32(0x76446B0)}")
