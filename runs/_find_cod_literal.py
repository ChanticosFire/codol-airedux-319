"""Locate the literal "cod" in the client image and find code that references it.

Round 215 showed that changing configstring[2] from "cod" to "abc" (same length)
makes the client drop from net=8 to net=0.  So either that string is validated as
a product tag, or the gamestate has a whole-packet checksum.  This script maps the
literal to a virtual address and searches .text for immediate references to it.
"""
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
FILE_OFFSET = 0x9B2EFC

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()

# map file offset -> virtual address
va = None
section_name = None
for s in pe.sections:
    lo = s.PointerToRawData
    hi = lo + s.SizeOfRawData
    if lo <= FILE_OFFSET < hi:
        va = base + s.VirtualAddress + (FILE_OFFSET - lo)
        section_name = s.Name.rstrip(b"\x00").decode("latin-1")
        break
print("  literal at file offset %#x -> section %s  VA %s" % (
    FILE_OFFSET, section_name, hex(va) if va else None))

raw = d[FILE_OFFSET:FILE_OFFSET + 8]
print("  bytes around it:", d[FILE_OFFSET - 8:FILE_OFFSET + 8].hex(" "))
print("  as text:", repr(d[FILE_OFFSET - 8:FILE_OFFSET + 8]))

if va is None:
    raise SystemExit("no VA")

# search whole image for the little-endian VA (immediate used by push/mov)
needle = struct.pack("<I", va)
hits = []
p = 0
while True:
    j = d.find(needle, p)
    if j < 0:
        break
    hits.append(j)
    p = j + 1
print()
print("  immediate references to that VA: %d" % len(hits))
for j in hits[:16]:
    # map to VA
    for s in pe.sections:
        lo = s.PointerToRawData
        hi = lo + s.SizeOfRawData
        if lo <= j < hi:
            cva = base + s.VirtualAddress + (j - lo)
            print("    file %#x -> VA %#x  (section %s)" % (
                j, cva, s.Name.rstrip(b"\x00").decode("latin-1")))
            break
