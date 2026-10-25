"""Hook user32!GetKeyboardState via the client's IAT so the game sees our keys.

Why: the client reads the keyboard with GetKeyboardState, which returns the key
state of the *calling thread's* message queue.  The render/logic thread never
pumps keyboard messages, so SendInput-injected keys are invisible to it.  We
rewrite the IAT slot so every call goes through our stub, which calls the real
function and then overwrites the requested bytes from a small config table.

Stub layout (x86, stdcall, 1 arg):
    push ebp / mov ebp,esp / push esi,edi,ebx
    push [ebp+8] ; mov eax,[ORIG] ; call eax
    test eax,eax ; jz done
    mov edi,[ebp+8] ; mov esi,CFG ; xor ecx,ecx
  loop: mov al,[esi+ecx] ; test al,al ; jz skip ; mov [edi+ecx],al
  skip: inc ecx ; cmp ecx,256 ; jb loop
  done: pop ebx,edi,esi ; mov esp,ebp ; pop ebp ; ret 4

Usage:
    python runs/_hook_getkeyboardstate.py <pid> [vk,hex ...]
    e.g. ... 2956 0x57 0x20      -> force W and SPACE
Config table is 256 bytes at CFG; entry i = value to force for VK i (0 = leave).
"""
import ctypes
import struct
import sys

from ctypes import wintypes as W

pid = int(sys.argv[1])
vks = [int(x, 0) for x in sys.argv[2:]] or [0x57]
EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"

k = ctypes.WinDLL("kernel32")
k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(0x43A, False, pid)   # VM_OP | VM_READ | VM_WRITE | VM_OPERATION
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


def alloc(n, protect):
    k.VirtualAllocEx.restype = ctypes.c_void_p
    return k.VirtualAllocEx(h, None, n, 0x3000, protect)


# ---- 1. find module base ----
base = None
head = rd(0x400000, 2)
if head == b"MZ":
    base = 0x400000
else:
    # fall back: scan a few likely bases
    for b in (0x400000, 0x10000000, 0x00400000):
        if rd(b, 2) == b"MZ":
            base = b
            break
print("  module base = %s" % (hex(base) if base else None))
if not base:
    raise SystemExit("cannot find module base")

# ---- 2. locate the GetKeyboardState IAT slot with pefile ----
import pefile

pe = pefile.PE(EXE, fast_load=True)
pe.parse_data_directories()
iat_va = None
orig_fn = None
for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    if entry.dll.decode("latin-1").lower() != "user32.dll":
        continue
    for imp in entry.imports:
        if imp.name and imp.name.decode("latin-1") == "GetKeyboardState":
            iat_va = base + imp.address          # imp.address is an RVA of the IAT slot
            orig_fn = struct.unpack("<I", rd(iat_va, 4))[0]
print("  IAT slot for GetKeyboardState = %s" % (hex(iat_va) if iat_va else None))
print("  current target               = %s" % (hex(orig_fn) if orig_fn else None))
if not iat_va or not orig_fn:
    raise SystemExit("GetKeyboardState import not found")

# ---- 3. allocate stub + config ----
PAGE_RWX = 0x40
PAGE_RW = 0x04
stub = alloc(0x400, PAGE_RWX)
cfg = alloc(0x400, PAGE_RW)
if not stub or not cfg:
    raise SystemExit("VirtualAllocEx failed")
print("  stub = %#x   cfg = %#x" % (stub, cfg))

# ---- 4. build stub ----
code = bytearray()
code += b"\x55"                                  # push ebp
code += b"\x8B\xEC"                              # mov ebp, esp
code += b"\x53"                                  # push ebx
code += b"\x56"                                  # push esi
code += b"\x57"                                  # push edi
code += b"\xFF\x75\x08"                          # push dword [ebp+8]
code += b"\xA1" + struct.pack("<I", orig_fn)     # mov eax, [orig_fn]
code += b"\xFF\xD0"                              # call eax
code += b"\x85\xC0"                              # test eax, eax
jz_pos = len(code)
code += b"\x74\x00"                              # jz done (patch later)
code += b"\x8B\x7D\x08"                          # mov edi, [ebp+8]
code += b"\xBE" + struct.pack("<I", cfg)         # mov esi, cfg
code += b"\x31\xC9"                              # xor ecx, ecx
loop_top = len(code)
code += b"\x8A\x04\x0E"                          # mov al, [esi+ecx]
code += b"\x84\xC0"                              # test al, al
code += b"\x74\x03"                              # jz skip
code += b"\x88\x04\x0F"                          # mov [edi+ecx], al
code += b"\x41"                                  # inc ecx
code += b"\x81\xF9\x00\x01\x00\x00"              # cmp ecx, 256
jb_pos = len(code)
code += b"\x72\x00"                              # jb loop_top (patch later)
done = len(code)
code += b"\x5F"                                  # pop edi
code += b"\x5E"                                  # pop esi
code += b"\x5B"                                  # pop ebx
code += b"\x8B\xE5"                              # mov esp, ebp
code += b"\x5D"                                  # pop ebp
code += b"\xC2\x04\x00"                          # ret 4

code[jz_pos + 1] = (done - (jz_pos + 2)) & 0xFF
code[jb_pos + 1] = (loop_top - (jb_pos + 2)) & 0xFF

ok, n = wr(stub, bytes(code))
print("  stub written (%d bytes, ok=%s)" % (len(code), ok))

# ---- 5. config: force the requested VKs ----
cfgbuf = bytearray(256)
for vk in vks:
    cfgbuf[vk] = 0x80
ok, n = wr(cfg, bytes(cfgbuf))
print("  cfg written: forcing %s" % [hex(v) for v in vks])

# ---- 6. patch the IAT ----
ok, n = wr(iat_va, struct.pack("<I", stub))
print("  IAT patched -> %#x (ok=%s)" % (stub, ok))
now = struct.unpack("<I", rd(iat_va, 4))[0]
print("  verify IAT now = %#x  %s" % (now, "OK" if now == stub else "MISMATCH"))
print()
print("  Keys are now forced. Sample cl for forwardmove with:")
print("    python runs\\_find_forwardmove.py %d" % pid)
