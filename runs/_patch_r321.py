"""Round 111: bypass the faulting dereference at 0x454A8B.

Root cause (Round 110):
    edx = [0x82C3B58]                  ; index
    eax = [edx*4 + 0x1C1D188]          ; table in .data — all entries are 0
    eax ^= 0xFBB2C97A                  ; 0 ^ key = 0xFBB2C97A  (bogus pointer)
    cmp byte [eax + 0x180C1C], 2       ; reads 0xFBCAD596 -> access violation

Fix: turn the following `jne 0x454B3F` into an unconditional `jmp 0x454B3F`,
so the invalid dereference is never executed.

    0x454A92: 0F 85 A7 00 00 00  (jne +0xA7)  ->  E9 A8 00 00 00 90  (jmp +0xA8)

Usage: python runs/_patch_r321.py <pid>
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


print("=== table state (should be zeros) ===")
idx = u32(0x82C3B58)
print(f"  [0x82C3B58] (index edx) = {idx}")
if idx is not None:
    ent = u32((0x1C1D188 + idx * 4) & 0xFFFFFFFF)
    print(f"  table entry [{idx}] = {ent}")
    if ent is not None:
        print(f"  decrypted pointer    = {ent ^ 0xFBB2C97A:#x}  (0xFBB2C97A is bogus)")

print()
print("=== patches ===")
patch(0x5C2303, bytes.fromhex("0f8c0a010000"), b"\x90" * 6, "net_state>=7 gate")
patch(0x5C23FF, bytes.fromhex("8d9000feffff"), bytes.fromhex("31d290909090"), "serial window")
patch(0x5C265F, bytes.fromhex("e86cfeffff"), b"\x90" * 5, "NOP timeout handler")
patch(0x515738, bytes.fromhex("8b8e50010800"), bytes.fromhex("31c990909090"),
      "neutralise [conn+0x80150]")
patch(0x51573E, bytes.fromhex("8b9648010800"), bytes.fromhex("31d290909090"),
      "neutralise [conn+0x80148]")
# THE KEY PATCH
patch(0x454A92, bytes.fromhex("0f85a7000000"), bytes.fromhex("e9a800000090"),
      "force jmp past the bogus-pointer dereference")

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
