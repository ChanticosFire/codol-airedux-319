"""Dump the spectator-related strings and find code that references them.

Goal: locate the code path that decides "this client is a spectator", because
every scenario so far renders the 3D world but shows the spectator hints
("Q next player / E previous player") instead of a controllable first person.
"""
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()


def va_of(off):
    for s in pe.sections:
        lo = s.PointerToRawData
        hi = lo + s.SizeOfRawData
        if lo <= off < hi:
            return base + s.VirtualAddress + (off - lo)
    return None


candidates = []
for needle in (b"spectator", b"Spectator", b"SPECTATOR"):
    p = 0
    while True:
        j = d.find(needle, p)
        if j < 0:
            break
        candidates.append((needle, j))
        p = j + 1

print("=== string contents ===")
seen = set()
for needle, off in candidates:
    if off in seen:
        continue
    seen.add(off)
    end = d.find(b"\x00", off)
    s = d[off:end]
    va = va_of(off)
    print("  %#010x  %-12r  %r" % (va or 0, needle, s[:70]))

print()
print("=== code references (imm32 == VA) ===")
for needle, off in candidates:
    va = va_of(off)
    if not va:
        continue
    imm = struct.pack("<I", va)
    refs = []
    p = 0
    while True:
        j = d.find(imm, p)
        if j < 0:
            break
        rva = va_of(j)
        name = ""
        for s in pe.sections:
            lo, hi = s.PointerToRawData, s.PointerToRawData + s.SizeOfRawData
            if lo <= j < hi:
                name = s.Name.rstrip(b"\x00").decode("latin-1")
                break
        if name == ".text":
            refs.append(rva)
        p = j + 1
    if refs:
        print("  %r (VA %#x): %d .text refs" % (needle, va, len(refs)))
        for r in refs[:8]:
            print("      %#010x" % r)
