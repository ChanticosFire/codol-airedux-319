"""Hook user32!GetKeyboardState through the client's IAT (robust version).

The client reads the keyboard with GetKeyboardState, which reports the key state
of the *calling thread's* message queue.  The render/logic thread never pumps
keyboard messages, so SendInput-injected keys are invisible to it.  This stub
calls the real function then overwrites the requested bytes from a config table,
so the game genuinely sees the keys as held.

Module bases come from EnumProcessModules (not a guessed 0x400000), and the real
GetKeyboardState address is derived from user32's export table in memory, so the
IAT read cannot dangle.
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

PROCESS_ALL = 0x1F0FFF
k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(PROCESS_ALL, False, pid)
if not h:
    raise SystemExit("OpenProcess failed: %d" % ctypes.get_last_error())


def rd(a, n):
    b = ctypes.create_string_buffer(n)
    g = ctypes.c_size_t()
    if not k.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(g)):
        return None
    return b.raw


def wr(a, data):
    g = ctypes.c_size_t()
    buf = ctypes.create_string_buffer(data, len(data))
    ok = k.WriteProcessMemory(h, ctypes.c_void_p(a), buf, len(data), ctypes.byref(g))
    return bool(ok), g.value


def u32(a):
    b = rd(a, 4)
    return struct.unpack("<I", b)[0] if b else None


# ---------- 1. enumerate modules ----------

psapi.EnumProcessModulesEx.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD), W.DWORD]
psapi.GetModuleBaseNameW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
psapi.GetModuleBaseNameW.restype = W.DWORD
psapi.EnumProcessModulesEx.restype = W.BOOL
hmods = (W.HMODULE * 1024)()
needed = W.DWORD()
if not psapi.EnumProcessModulesEx(h, ctypes.byref(hmods), ctypes.sizeof(hmods),
                                 ctypes.byref(needed), 0x03):
    raise SystemExit("EnumProcessModulesEx failed: %d" % ctypes.get_last_error())
count = needed.value // ctypes.sizeof(W.HMODULE)

mods = {}
for i in range(count):
    hmod = hmods[i]
    namebuf = ctypes.create_unicode_buffer(260)
    if psapi.GetModuleBaseNameW(h, hmod, namebuf, 260):
        mods[namebuf.value.lower()] = hmod
print("  modules: %d" % count)
for name in list(mods)[:12]:
    print("    %-34s %#x" % (name, mods[name]))

exe_name = EXE.split("\\")[-1].lower()
exe_base = mods.get(exe_name)
u32_base = mods.get("user32.dll")
print()
print("  exe base   = %s" % (hex(exe_base) if exe_base else None))
print("  user32 base= %s" % (hex(u32_base) if u32_base else None))
if not exe_base or not u32_base:
    raise SystemExit("needed modules missing")

# ---------- 2. GetKeyboardState real address from user32 exports ----------
import pefile

u32_path = r"C:\Windows\SysWOW64\user32.dll"
pe32 = pefile.PE(u32_path, fast_load=True)
pe32.parse_data_directories()
gks_rva = None
for exp in getattr(pe32, "DIRECTORY_ENTRY_EXPORT", []).symbols:
    if exp.name and exp.name.decode("latin-1") == "GetKeyboardState":
        gks_rva = exp.address
        break
print("  GetKeyboardState RVA in user32 = %s" % (hex(gks_rva) if gks_rva else None))
if gks_rva is None:
    raise SystemExit("export not found")
orig_fn = u32_base + gks_rva
print("  GetKeyboardState real address = %#x" % orig_fn)

# ---------- 3. IAT slot in the exe ----------
pe = pefile.PE(EXE, fast_load=True)
pe.parse_data_directories()
iat_va = None
for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    if entry.dll.decode("latin-1").lower() != "user32.dll":
        continue
    for imp in entry.imports:
        if imp.name and imp.name.decode("latin-1") == "GetKeyboardState":
            iat_va = exe_base + imp.address
            break
print("  IAT slot = %s" % (hex(iat_va) if iat_va else None))
if not iat_va:
    raise SystemExit("import not found")
cur = u32(iat_va)
print("  IAT now  = %s  (expected %#x)" % (hex(cur) if cur else None, orig_fn))
if cur is None:
    print("  WARN: cannot read IAT slot; will still try to patch")

# ---------- 4. allocate stub + config ----------
k.VirtualAllocEx.restype = ctypes.c_void_p
stub = k.VirtualAllocEx(h, None, 0x400, 0x3000, 0x40)   # RWX
cfg = k.VirtualAllocEx(h, None, 0x400, 0x3000, 0x04)    # RW
if not stub or not cfg:
    raise SystemExit("VirtualAllocEx failed")
print("  stub = %#x   cfg = %#x" % (stub, cfg))

# ---------- 5. build stub ----------
code = bytearray()
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
code += b"\x74\x00"                               # jz done
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
code += b"\x72\x00"                               # jb loop_top
done = len(code)
code += b"\x5F"                                   # pop edi
code += b"\x5E"                                   # pop esi
code += b"\x5B"                                   # pop ebx
code += b"\x8B\xE5"                               # mov esp,ebp
code += b"\x5D"                                   # pop ebp
code += b"\xC2\x04\x00"                           # ret 4
code[jz_pos + 1] = (done - (jz_pos + 2)) & 0xFF
code[jb_pos + 1] = (loop_top - (jb_pos + 2)) & 0xFF

ok, _ = wr(stub, bytes(code))
print("  stub written %d bytes ok=%s" % (len(code), ok))

# ---------- 6. config ----------
cfgbuf = bytearray(256)
for vk in vks:
    cfgbuf[vk] = 0x80
ok, _ = wr(cfg, bytes(cfgbuf))
print("  cfg forcing %s ok=%s" % ([hex(v) for v in vks], ok))

# ---------- 7. patch IAT ----------
ok, _ = wr(iat_va, struct.pack("<I", stub))
print("  IAT patched -> %#x ok=%s" % (stub, ok))
now = u32(iat_va)
print("  verify IAT = %s  %s" % (hex(now) if now else None,
                                 "OK" if now == stub else "MISMATCH"))
print()
print("  config page = %#x (byte i = value forced for VK i)" % cfg)
