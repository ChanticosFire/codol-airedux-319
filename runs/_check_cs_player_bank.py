"""Check whether build 1649370 also uses configstring bank 0x6C7 + clientIndex.

The 2.6.9.7 reference doc says the player-name configstring bank is
`0x6c7 + clientIndex`, and that the client copies it around 0x471d60.
Our build's CL_ParseSnapshot sits at 0x471E90, i.e. the same neighbourhood.

This script:
  1. searches .text for immediates 0x6C7 / 0x6c7+1-ish and reports sites
  2. disassembles around 0x471D60 to see how the client indexes configstrings
  3. looks for the (0x6C7 + something) pattern via `lea reg,[base + idx]`
"""
import pefile
import capstone
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
text = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
code = d[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
text_va = base + text.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

print("=== immediate 0x6C7 (1735) in .text ===")
pat = struct.pack("<I", 0x6C7)
hits = []
p = 0
while True:
    i = code.find(pat, p)
    if i < 0:
        break
    hits.append(text_va + i)
    p = i + 1
print("  hits: %d" % len(hits))
for a in hits[:20]:
    print("    %#010x" % a)

print()
print("=== disassembly around 0x471D60 (doc says configstring copy happens here) ===")
start = 0x471D00
o = start - text_va
n = 0
for ins in md.disasm(code[o:o + 0x100], start):
    mark = ""
    if ins.mnemonic in ("mov", "lea") and ("0x6c7" in ins.op_str or "0x6C7" in ins.op_str):
        mark = "   <<<<<< 0x6C7"
    if ins.address >= 0x471D40 and ins.address <= 0x471DA0:
        print("  %#010x  %-22s %-6s %s%s" % (ins.address, ins.bytes.hex(" "),
                                              ins.mnemonic, ins.op_str, mark))
    n += 1
    if n > 60:
        break
