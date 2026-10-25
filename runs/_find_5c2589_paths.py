"""Find EVERY way control can reach 0x5C2589, including indirect jumps.

Round 92 proved:
  * the NOP at 0x5C2530 stays in place (bytes = 90 90),
  * the translation table 0x4F2760 is never called,
  * yet Com_Error receives arg1 = 0xDBB658,
so some path other than the patched jl must reach 0x5C2589.

A linear disassembly sweep can miss targets when it starts mid-instruction, so
this script also does a byte-level scan for E8/E9/EB rel8/rel32 and for
jump-table entries (any 4-byte value equal to the target inside .rdata/.text).
"""
import pefile
import re
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
TARGET = 0x5C2589

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()


def section_for(va):
    for s in pe.sections:
        lo = s.VirtualAddress + base
        if lo <= va < lo + s.Misc_VirtualSize:
            return s, lo
    return None, None


s, lo = section_for(TARGET)
print(f"target {TARGET:#x} is in section {s.Name!r}")

# --- 1) relative branches whose destination is TARGET -------------------------
t = [x for x in pe.sections if x.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress

hits = []
# E8/E9 rel32
for m in re.finditer(rb"[\xe8\xe9]", code):
    i = m.start()
    if i + 5 > len(code):
        continue
    rel = struct.unpack_from("<i", code, i + 1)[0]
    dest = (text_va + i + 5 + rel) & 0xFFFFFFFF
    if dest == TARGET:
        hits.append((text_va + i, "E8/E9 rel32"))
# EB rel8
for m in re.finditer(rb"\xeb", code):
    i = m.start()
    if i + 2 > len(code):
        continue
    rel = struct.unpack_from("<b", code, i + 1)[0]
    dest = (text_va + i + 2 + rel) & 0xFFFFFFFF
    if dest == TARGET:
        hits.append((text_va + i, "EB rel8"))
# 0F 8x rel32
for m in re.finditer(rb"\x0f[\x80-\x8f]", code):
    i = m.start()
    if i + 6 > len(code):
        continue
    rel = struct.unpack_from("<i", code, i + 2)[0]
    dest = (text_va + i + 6 + rel) & 0xFFFFFFFF
    if dest == TARGET:
        hits.append((text_va + i, "0F 8x rel32"))
# 7x rel8
for m in re.finditer(rb"[\x70-\x7f]", code):
    i = m.start()
    if i + 2 > len(code):
        continue
    rel = struct.unpack_from("<b", code, i + 1)[0]
    dest = (text_va + i + 2 + rel) & 0xFFFFFFFF
    if dest == TARGET:
        hits.append((text_va + i, "7x rel8"))

print()
print(f"=== relative branches to {TARGET:#x}: {len(hits)} ===")
for a, kind in sorted(hits):
    print(f"  {a:#010x}  {kind}")

# --- 2) any 4-byte little-endian value == TARGET (jump tables / vtable slots) --
needle = struct.pack("<I", TARGET)
print()
print("=== 4-byte occurrences of the target address (jump tables) ===")
for s2 in pe.sections:
    name = s2.Name.rstrip(b"\x00")
    if name == b".text":
        continue
    body = d[s2.PointerToRawData:s2.PointerToRawData + s2.SizeOfRawData]
    for m in re.finditer(re.escape(needle), body):
        print(f"  {s2.VirtualAddress + base + m.start():#010x}  in {name!r}")

# --- 3) is 0x5C2589 perhaps a function entry reached by CALL? ------------------
print()
print("=== bytes around the target ===")
off = TARGET - text_va
print("  ", d[off - 8:off + 8].hex(" "))
print("   (note: 0x5C2583 is 'mov [esi+0x211E0], eax', so execution can FALL THROUGH into 0x5C2589)")
