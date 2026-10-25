"""Round 117: neutralise the dev-time assertion at 0x59B596.

Root cause found this round:
    0x59B594  cmp eax, edi          ; id returned by 0x42F3E0 vs the index
    0x59B596  jne 0x59B676          ; mismatch -> assertion failure
    0x59B679  push 0xDBF110         ; "181 %s %d %d"
    0x59B680  call 0x4F82E0         ; Com_Error(2, ...)  <- fatal

That is why the 1700-iteration loop dies on its FIRST pass (loop=1).

Fix: turn the `jne` into six NOPs so a mismatch just falls through.

    0x59B596: 0F 85 DA 00 00 00  ->  90 90 90 90 90 90

Usage: python runs/_patch_r325.py <pid>
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


print("=== patches ===")
patch(0x5C2303, bytes.fromhex("0f8c0a010000"), b"\x90" * 6, "net_state>=7 gate")
patch(0x5C23FF, bytes.fromhex("8d9000feffff"), bytes.fromhex("31d290909090"), "serial window")
patch(0x5C265F, bytes.fromhex("e86cfeffff"), b"\x90" * 5, "NOP timeout handler")
patch(0x515738, bytes.fromhex("8b8e50010800"), bytes.fromhex("31c990909090"),
      "neutralise [conn+0x80150]")
patch(0x51573E, bytes.fromhex("8b9648010800"), bytes.fromhex("31d290909090"),
      "neutralise [conn+0x80148]")
patch(0x454A92, bytes.fromhex("0f85a7000000"), bytes.fromhex("e9a800000090"),
      "force jmp in 0x454A92")
# THE KEY PATCH
patch(0x59B596, bytes.fromhex("0f85da000000"), b"\x90" * 6,
      "NOP the assertion branch in 0x59B560")

va = k.VirtualAllocEx(h, None, 256, 0x3000, 0x04)
if va and va < 0x100000000:
    s = b"mp_crash_tropical\x00"
    got = ctypes.c_size_t()
    k.WriteProcessMemory(h, ctypes.c_void_p(va),
                         ctypes.create_string_buffer(s, len(s)), len(s), ctypes.byref(got))
    BASE = 0x80FC008
    patch(BASE + 12, struct.pack("<I", u32(BASE + 12) or 0),
          struct.pack("<I", va), "ui_mapname valptr")

FLAG = 0xC7341DB
prot = W.DWORD()
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, 0x40, ctypes.byref(prot))
got = ctypes.c_size_t()
k.WriteProcessMemory(h, ctypes.c_void_p(FLAG), ctypes.create_string_buffer(b"\x00", 1), 1,
                     ctypes.byref(got))
k.VirtualProtectEx(h, ctypes.c_void_p(FLAG), 1, prot.value, ctypes.byref(prot))

enc = u32(0x331C0C8)
conn = (enc ^ 0xD362501F) if enc else 0
if 0x10000 <= conn < 0x7FFF0000:
    adr = struct.pack("<I4sHHIII", 2, b"\0\0\0\0", 0, 0, 0, 0, 0x9D)
    k.WriteProcessMemory(h, ctypes.c_void_p(conn + 0x14),
                         ctypes.create_string_buffer(adr, len(adr)), len(adr),
                         ctypes.byref(got))
    print(f"  conn={conn:#x} adr written")
print(f"  net_state = {u32(0x76446B0)}")
