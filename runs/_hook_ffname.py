"""Collect every fastfile name that CODOL actually requests.

`0x49ED40` is `FS_LoadFastfile(name)`; it builds the real file name with
`sprintf(buf, "%s.ff", name)` at `0x49ED71`, leaving the result in `[ebp-0x108]`.

Hooking `0x49ED76` (`add esp,0x10 ; mov esi,ebx`, exactly 5 bytes) lands right
*after* the sprintf, so the cave can copy the finished name out:

    pushad
    mov  eax, [count]
    imul eax, eax, 64
    add  eax, DST
    mov  edi, eax
    lea  esi, [ebp-0x108]
    mov  ecx, 16           ; 64 bytes
    rep  movsb
    inc  dword [count]
    popad
    add  esp, 0x10         ; replay
    mov  esi, ebx          ; replay
    jmp  0x49ED7B

Usage:
  python runs/_hook_ffname.py <pid> --install
  python runs/_hook_ffname.py <pid> --read
  python runs/_hook_ffname.py <pid> --restore
"""
import argparse
import ctypes
import struct
import sys
from ctypes import wintypes as W

SITE = 0x49ED76
BACK = 0x49ED7B
ORIG = bytes.fromhex("83c4108bf3")      # add esp,0x10 ; mov esi,ebx
COUNT = 0xE54E000
DST = 0xE54E100
STRIDE = 64
MAXN = 40

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.restype = W.HANDLE
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.WriteProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.VirtualAllocEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD, W.DWORD]
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualProtectEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t, W.DWORD,
                               ctypes.POINTER(W.DWORD)]
k.FlushInstructionCache.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_size_t]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int)
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    h = k.OpenProcess(0x1F0FFF, False, args.pid)
    if not h:
        raise SystemExit("OpenProcess failed")

    def read(addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
            return None
        return buf.raw

    def write(addr, blob):
        got = ctypes.c_size_t()
        return bool(k.WriteProcessMemory(h, ctypes.c_void_p(addr),
                                         ctypes.create_string_buffer(blob, len(blob)),
                                         len(blob), ctypes.byref(got)))

    def u32(addr):
        d = read(addr, 4)
        return struct.unpack("<I", d)[0] if d else None

    cur = read(SITE, 5)
    print("site bytes now:", cur.hex() if cur else None,
          "| is_original:", cur == ORIG)

    if args.read:
        n = u32(COUNT) or 0
        print("count =", n)
        for i in range(min(n, MAXN)):
            raw = read(DST + i * STRIDE, STRIDE) or b""
            name = raw.split(b"\x00")[0]
            print(f"  [{i:2d}] {name!r}")
        return

    if args.restore:
        old = W.DWORD()
        k.VirtualProtectEx(h, ctypes.c_void_p(SITE), len(ORIG), 0x40, ctypes.byref(old))
        ok = write(SITE, ORIG)
        k.VirtualProtectEx(h, ctypes.c_void_p(SITE), len(ORIG), old.value, ctypes.byref(old))
        k.FlushInstructionCache(h, ctypes.c_void_p(SITE), len(ORIG))
        print("restored:", ok, read(SITE, 5).hex())
        return

    if not args.install:
        print("nothing to do; pass --install / --read / --restore")
        return

    cave = int(k.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40) or 0)
    if not cave:
        raise SystemExit("VirtualAllocEx failed")

    code = bytearray()
    code += b"\x60"                                        # pushad
    code += b"\xA1" + struct.pack("<I", COUNT)             # mov eax,[count]
    code += b"\x6B\xC0" + struct.pack("<B", STRIDE)        # imul eax,eax,STRIDE
    code += b"\x05" + struct.pack("<I", DST)               # add eax,DST
    code += b"\x8B\xF8"                                    # mov edi,eax
    code += b"\x8D\xB5\xF8\xFE\xFF\xFF"                    # lea esi,[ebp-0x108]
    code += b"\xB9" + struct.pack("<I", STRIDE // 4)       # mov ecx,STRIDE/4
    code += b"\xF3\xA5"                                    # rep movsd
    code += b"\xFF\x05" + struct.pack("<I", COUNT)         # inc dword [count]
    code += b"\x61"                                        # popad
    code += ORIG                                           # replay
    rel = (BACK - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)               # jmp back

    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k.FlushInstructionCache(h, ctypes.c_void_p(cave), len(code))

    write(COUNT, b"\x00\x00\x00\x00")
    old = W.DWORD()
    k.VirtualProtectEx(h, ctypes.c_void_p(SITE), 5, 0x40, ctypes.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (SITE + 5)) & 0xFFFFFFFF)
    ok = write(SITE, jump)
    k.VirtualProtectEx(h, ctypes.c_void_p(SITE), 5, old.value, ctypes.byref(old))
    k.FlushInstructionCache(h, ctypes.c_void_p(SITE), 5)
    print("installed:", ok, "cave:", hex(cave), "->", read(SITE, 5).hex())


if __name__ == "__main__":
    main()
