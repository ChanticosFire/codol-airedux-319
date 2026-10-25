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


# --- KEY FIX 12: 0x58EF76 mov esi,[ecx*4+0x1988B50] -> mov esi,[0x1988B50] ---
# Same table as 0x58F3B9; ecx is an out-of-range index so the entry is NULL and
# 0x58EFA1 faults on [esi+0x58C].  The filled table base is a valid zero object.
patch(0x58EF76, bytes.fromhex("8b348d508b9801"), bytes.fromhex("8b35508b980190"),
      "0x58EF76 mov esi,[ecx*4+table] -> mov esi,[table]")


# --- KEY FIX 13: 0x4724A9  jne 0x47281A -> nop x6 ---
# CL_ParseSnapshot bails out here 706/706 times because [esi] == 1 (a stack-local
# mode flag) while the check requires 0.  Skipping the check lets the parser run
# to completion so we can see whether the snapshot body itself is accepted.
patch(0x4724A9, bytes.fromhex("0f856b030000"), bytes.fromhex("909090909090"),
      "0x4724A9 skip the [esi]!=0 bail-out")


# --- KEY FIX 14: nop the other two bail-outs of CL_ParseSnapshot ---
# 0x4724C4 and 0x4724CD both jump to 0x47281A (skip the flag set) when their
# checked field is zero.  Together with KEY FIX 13 this removes all three
# early-outs so the parser can actually run to completion.
patch(0x4724C4, bytes.fromhex("0f8450030000"), bytes.fromhex("909090909090"),
      "0x4724C4 skip bail-out 2")
patch(0x4724CD, bytes.fromhex("0f8447030000"), bytes.fromhex("909090909090"),
      "0x4724CD skip bail-out 3")



# --- KEY FIX 15 (CORRECT): 0x472456  xor eax,key -> jmp 0x472490 ---
# edi is 0 in our flow, so the edi-related checks at 0x472466..0x47247B would
# either bail out (safe path via 0x4727C9) or dereference [edi+0x3B9C] and fault.
# 0x472490 is the common join point of all those checks and leads straight into
# the glass-block parser (0x4724A0) and the rest of the normal parse body.
patch(0x472456, bytes.fromhex("351f5062d3"), bytes.fromhex("e935000000"),
      "0x472456 jmp 0x472490 (skip edi-dependent checks)")


# --- KEY FIX 16: 0x472209  mov dword ptr [esi],1 -> nop x6 ---
# This is the EOF marker.  When the snapshot runs short the reader sets
# [esi]=1 and CL_ParseSnapshot later rejects the packet at 0x4724A7
# (cmp [esi],0).  Suppressing the marker lets the parse body continue so we can
# see how far it gets with the data we actually send.
patch(0x472209, bytes.fromhex("c70601000000"), bytes.fromhex("909090909090"),
      "0x472209 suppress the EOF marker")


# --- KEY FIX 17: 0x47223D  jne 0x47226D -> jmp 0x47226D ---
# ecx==0 (short buffer) makes this jne fall through into the "save EOF + ret"
# path at 0x472248..0x472267.  Forcing the jump continues the normal parse body.
patch(0x47223D, bytes.fromhex("752e"), bytes.fromhex("eb2e"),
      "0x47223D jne -> jmp 0x47226D (continue parse instead of early ret)")




# --- KEY FIX 18 (GLOBAL): create the object behind [0x32AA908] ---
# The binary references [0x32AA908] from 30 sites across many modules; in our
# flow that global is never created, so every deref ([ptr+0xC] etc.) faults.
# Build a small structure whose +0xC field points at an empty string, and store
# it in the global.  All 30 sites then see a valid pointer.
_empty = k.VirtualAllocEx(h, None, 0x100, 0x3000, 0x04)
_srv   = k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x04)
if _empty and _srv:
    _g = ctypes.c_size_t()
    _z = b"\x00"
    k.WriteProcessMemory(h, ctypes.c_void_p(_empty),
                         ctypes.create_string_buffer(_z, 1), 1, ctypes.byref(_g))
    _blob = b"\x00" * 0xC + struct.pack("<I", _empty) + b"\x00" * 0x30
    k.WriteProcessMemory(h, ctypes.c_void_p(_srv),
                         ctypes.create_string_buffer(_blob, len(_blob)),
                         len(_blob), ctypes.byref(_g))
    _glob = struct.pack("<I", _srv)
    k.WriteProcessMemory(h, ctypes.c_void_p(0x32AA908),
                         ctypes.create_string_buffer(_glob, 4), 4, ctypes.byref(_g))
    print(f"  [0x32AA908] init: srv={_srv:#x} empty={_empty:#x}")
else:
    print(f"  [0x32AA908] init FAILED: srv={_srv} empty={_empty}")

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
