"""Scan the whole .text for references to the table at 0x1988B50.

Two crashes so far had the identical shape:
    0x42F364  eax = [ebx*4 + 0x1988B50]   0x42F36B  esi = [eax]   (NULL deref)
    0x58F3B9  ecx = [ecx*4 + 0x1988B50]   0x58F3C0  esi = [ecx]   (NULL deref)

The table is an object list that is empty in our scenario, so every consumer
that dereferences the fetched entry can fault.  Enumerate them all so they can be
guarded in one pass.

Usage: python runs/_scan_table_1988b50.py
"""
import capstone
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
TABLE = 0x1988B50

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

# --- 1) raw byte search for the little-endian immediate ---
raw = struct.pack("<I", TABLE)
hits = []
p = 0
while True:
    j = code.find(raw, p)
    if j < 0:
        break
    hits.append(text_va + j)
    p = j + 1
print(f"raw occurrences of {TABLE:#x} in .text: {len(hits)}")
for h in hits:
    print(f"  {h:#010x}")
print()

# --- 2) linear disassembly, find instructions whose operand mentions the table ---
print("=== instructions referencing the table, with the NEXT 3 instructions ===")
targets = set(h - 2 for h in hits) | set(h - 4 for h in hits) | set(h - 6 for h in hits)
off0 = 0
insns = list(md.disasm(code[0:len(code)], text_va))
by_addr = {i.address: k for k, i in enumerate(insns)}
found = 0
for k, ins in enumerate(insns):
    if str(TABLE) in ins.op_str or f"{TABLE:#x}" in ins.op_str:
        found += 1
        print(f"\n--- #{found} at {ins.address:#010x} ---")
        for m in range(k, min(k + 4, len(insns))):
            mark = "  <-- TABLE" if m == k else ""
            print(f"  {insns[m].address:#010x}  {insns[m].mnemonic:6s} {insns[m].op_str}{mark}")
print(f"\ntotal instruction-level references: {found}")
