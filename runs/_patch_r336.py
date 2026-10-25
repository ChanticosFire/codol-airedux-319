"""Round 131: the two structural fixes that should unblock the load path.

1) 0x42F32C: 73 23 (jae +0x23)  ->  EB 23 (jmp +0x23)
   Root cause (Round 130): the guarded path does
       edx = [esi*4 + 0x1988B50]   -> .data zero page -> 0
       edx = [edx]                  -> read address 0 -> access violation
   With the table entry always 0 in our scenario, the path must be skipped
   unconditionally.

2) 0x59B560: 55 8b ec 56 ...  ->  C3 90 ...
   That whole "assert id == index" validation function faults inside
   0x42F3E0 -> 0x42F2F0 on the first of 1700 iterations (Round 125/129).
   Skipping it lets the loop complete (cond=1699 measured).

Usage: python runs/_patch_r336.py <pid>
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

# --- KEY FIX 1: skip the null-pointer dereference path ---
patch(0x42F32C, bytes.fromhex("7323"), bytes.fromhex("eb23"),
      "0x42F32C jae -> jmp (skip null deref)")

# --- KEY FIX 2: skip the validation function entirely ---
patch(0x59B560, bytes.fromhex("558bec568db748170000"), bytes.fromhex("c3" + "90" * 9),
      "0x59B560 -> ret")


# --- KEY FIX 3: 0x42F36B  mov esi,[eax] -> xor esi,esi  (eax is a zero-page 0) ---
patch(0x42F36B, bytes.fromhex("8b30"), bytes.fromhex("31f6"),
      "0x42F36B mov esi,[eax] -> xor esi,esi")


# --- KEY FIX 4: 0x42F371  je 0x42F3A3 -> je 0x42F3BF (skip strncmp when esi==0) ---
patch(0x42F371, bytes.fromhex("7430"), bytes.fromhex("744c"),
      "0x42F371 je target -> loop exit 0x42F3BF")


# --- KEY FIX 5: 0x42F36D  je 0x42F3A3 -> je 0x42F3BF (the [ebp-1] branch) ---
patch(0x42F36D, bytes.fromhex("7434"), bytes.fromhex("7450"),
      "0x42F36D je target -> loop exit 0x42F3BF")


# --- KEY FIX 6: 0x432047  je -> jmp  (global [0x32AA908] is NULL) ---
patch(0x432047, bytes.fromhex("7432"), bytes.fromhex("eb32"),
      "0x432047 skip the NULL global deref")


# --- KEY FIX 11 (CORRECT ONE): 0x58F3B9 mov ecx,[ecx*4+0x1988B50] -> mov ecx,[0x1988B50] ---
# The real crash chain (Round 159):
#   0x58F3B9  ecx = [ecx*4 + 0x1988B50]   ; table entry = 0
#   0x58F3D0  [ebp-0x14] = ecx            ; = 0
#   0x58F557  esi = [ebp-0x14]            ; esi = 0   <-- the real zeroing site
#   0x58F55A  mov eax,[esi+0x7BC]         ; fault
# Loading the filled table base makes ecx valid for all downstream uses.
patch(0x58F3B9, bytes.fromhex("8b0c8d508b9801"), bytes.fromhex("8b0d508b9801 90".replace(" ", "")),
      "0x58F3B9 mov ecx,[ecx*4+table] -> mov ecx,[table]")

# --- KEY FIX 9: fill the 0x1988B50 table so lookups never return NULL ---
# The table is an object registry that our flow never populates (table=1 but
# consumers query index 1, 2, ...).  Allocate a large zero page and point every
# entry at it, so the 578 references all see a valid zero object.
_zobj = k.VirtualAllocEx(h, None, 0x10000, 0x3000, 0x04)
if _zobj and _zobj < 0x100000000:
    # make sure it is readable/writable and zeroed
    _zero = b"\x00" * 0x1000
    _got = ctypes.c_size_t()
    k.WriteProcessMemory(h, ctypes.c_void_p(_zobj),
                         ctypes.create_string_buffer(_zero, len(_zero)),
                         len(_zero), ctypes.byref(_got))
    TABLE_BASE = 0x1988B50
    ENTRIES = 256
    _blob = struct.pack("<I", _zobj) * ENTRIES
    _prot = W.DWORD()
    k.VirtualProtectEx(h, ctypes.c_void_p(TABLE_BASE), len(_blob), 0x40, ctypes.byref(_prot))
    _okw = k.WriteProcessMemory(h, ctypes.c_void_p(TABLE_BASE),
                                ctypes.create_string_buffer(_blob, len(_blob)),
                                len(_blob), ctypes.byref(_got))
    k.VirtualProtectEx(h, ctypes.c_void_p(TABLE_BASE), len(_blob), _prot.value, ctypes.byref(_prot))
    print(f"  TABLE fill: obj={_zobj:#x} entries={ENTRIES} ok={_okw}")
else:
    print(f"  TABLE fill FAILED: {_zobj}")


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
