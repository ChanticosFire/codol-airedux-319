"""Hook user32!GetKeyboardState with a CALL COUNTER, so we can prove whether the
client actually consults it.

Stub:
    inc byte [CNT]              ; FE 05 <cnt>
    push ebp / mov ebp,esp
    push ebx,esi,edi
    push [ebp+8] ; mov eax,[ORIG] ; call eax
    test eax,eax ; jz done
    mov edi,[ebp+8] ; mov esi,CFG ; xor ecx,ecx
  loop: mov al,[esi+ecx] ; test al,al ; jz skip ; mov [edi+ecx],al
  skip: inc ecx ; cmp ecx,256 ; jb loop
  done: pop edi,esi,ebx ; mov esp,ebp ; pop ebp ; ret 4

CNT lives at cfg+0x100 (outside the 256 VK bytes).
If CNT keeps growing, the game DOES call GetKeyboardState every frame and simply
ignores our forced keys -> look elsewhere.  If CNT stays 0, the game builds key
state from window messages instead.
"""
import ctypes
import struct
import sys

from ctypes import wintypes as W

pid = int(sys.argv[1])
vks = [int(x, 0) for x in sys.argv[2:]] or [0x57]
EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"

k = ctypes.WinDLL("kernel32")
psapi = ctypes.WinDLL("psapi")
psapi.EnumProcessModulesEx.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD,
                                       ctypes.POINTER(W.DWORD), W.DWORD]
psapi.GetModuleBaseNameW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
psapi.GetModuleBaseNameW.restype = W.DWORD

k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(0x1F0FFF, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        return None
    return b.raw


def wr(a, data):
    g = ctypes.c_size_t()
    buf = ctypes.create_string_buffer(data, len(data))
    return bool(k.WriteProcessMemory(h, ctypes.c_void_p(a), buf, len(data), ctypes.byref(g)))


def u32(a):
    b = rd(a, 4)
    return struct.unpack("<I", b)[0] if b else None


hmods = (W.HMODULE * 1024)()
need = W.DWORD()
if not psapi.EnumProcessModulesEx(h, ctypes.byref(hmods), ctypes.sizeof(hmods),
                                  ctypes.byref(need), 0x03):
    raise SystemExit("EnumProcessModulesEx failed")
mods = {}
for i in range(need.value // ctypes.sizeof(W.HMODULE)):
    nm = ctypes.create_unicode_buffer(260)
    if psapi.GetModuleBaseNameW(h, hmods[i], nm, 260):
        mods[nm.value.lower()] = hmods[i]

exe_base = mods.get(EXE.split("\\")[-1].lower())
u32_base = mods.get("user32.dll")
print("  exe=%s  user32=%s" % (hex(exe_base or 0), hex(u32_base or 0)))

import pefile

pe32 = pefile.PE(r"C:\Windows\SysWOW64\user32.dll", fast_load=True)
pe32.parse_data_directories()
gks_rva = next(e.address for e in pe32.DIRECTORY_ENTRY_EXPORT.symbols
               if e.name and e.name.decode("latin-1") == "GetKeyboardState")
orig_fn = u32_base + gks_rva
print("  GetKeyboardState = %#x" % orig_fn)

pe = pefile.PE(EXE, fast_load=True)
pe.parse_data_directories()
iat_va = None
for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    if entry.dll.decode("latin-1").lower() != "user32.dll":
        continue
    for imp in entry.imports:
        if imp.name and imp.name.decode("latin-1") == "GetKeyboardState":
            iat_va = exe_base + imp.address
print("  IAT slot = %#x" % iat_va)

k.VirtualAllocEx.restype = ctypes.c_void_p
stub = k.VirtualAllocEx(h, None, 0x400, 0x3000, 0x40)
cfg = k.VirtualAllocEx(h, None, 0x400, 0x3000, 0x04)
print("  stub=%#x cfg=%#x" % (stub, cfg))
cnt = cfg + 0x100

code = bytearray()
code += b"\xFE\x05" + struct.pack("<I", cnt)      # inc byte [cnt]
code += b"\x55"                                   # push ebp
code += b"\x8B\xEC"                               # mov ebp,esp
code += b"\x53"                                   # push ebx
code += b"\x56"                                   # push esi
code += b"\x57"                                   # push edi
code += b"\xFF\x75\x08"                           # push [ebp+8]
code += b"\xA1" + struct.pack("<I", orig_fn)      # mov eax,[orig]
code += b"\xFF\xD0"                               # call eax
code += b"\x85\xC0"                               # test eax,eax
jz_pos = len(code)
code += b"\x74\x00"
code += b"\x8B\x7D\x08"                           # mov edi,[ebp+8]
code += b"\xBE" + struct.pack("<I", cfg)          # mov esi,cfg
code += b"\x31\xC9"                               # xor ecx,ecx
loop_top = len(code)
code += b"\x8A\x04\x0E"                           # mov al,[esi+ecx]
code += b"\x84\xC0"                               # test al,al
code += b"\x74\x03"                               # jz skip
code += b"\x88\x04\x0F"                           # mov [edi+ecx],al
code += b"\x41"                                   # inc ecx
code += b"\x81\xF9\x00\x01\x00\x00"               # cmp ecx,256
jb_pos = len(code)
code += b"\x72\x00"
done = len(code)
code += b"\x5F\x5E\x5B"                           # pop edi,esi,ebx
code += b"\x8B\xE5\x5D"                           # mov esp,ebp ; pop ebp
code += b"\xC2\x04\x00"                           # ret 4
code[jz_pos + 1] = (done - (jz_pos + 2)) & 0xFF
code[jb_pos + 1] = (loop_top - (jb_pos + 2)) & 0xFF

print("  stub bytes:", len(code))
print("  stub write ok:", wr(stub, bytes(code)))

cfgbuf = bytearray(256)
for vk in vks:
    cfgbuf[vk] = 0x80
print("  cfg write ok:", wr(cfg, bytes(cfgbuf)))
print("  IAT patch ok:", wr(iat_va, struct.pack("<I", stub)))
print("  verify IAT =", hex(u32(iat_va) or 0))

print()
print("  counter at %#x, forcing %s" % (cnt, [hex(v) for v in vks]))
print("  reading counter 5x over 3s ...")
import time
for i in range(5):
    time.sleep(0.6)
    print("    t+%.1fs  calls=%s" % ((i + 1) * 0.6, u32(cnt) & 0xFF if u32(cnt) is not None else None))
