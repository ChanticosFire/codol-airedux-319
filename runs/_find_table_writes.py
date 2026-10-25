"""Find WRITE sites into the 0x1988B50 table (who fills it).

Rounds 141-142 showed two NULL-deref crashes both coming from reading this table
and finding 0, and that it is referenced from 578 places.  So the real fix is to
find who is supposed to populate it.

A write site looks like:
    mov dword ptr [reg*4 + 0x1988B50], <value>
i.e. the instruction's op_str has the table on the DESTINATION side.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
TABLE = 0x1988B50

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

needle = f"{TABLE:#x}"
insns = list(md.disasm(code, text_va))
reads = []
writes = []
for k, ins in enumerate(insns):
    if needle not in ins.op_str:
        continue
    # destination is the first operand
    dst = ins.op_str.split(",")[0].strip()
    if needle in dst and ins.mnemonic in ("mov", "lea"):
        if ins.mnemonic == "mov":
            writes.append((k, ins))
    else:
        reads.append((k, ins))

print(f"total references: {len(reads) + len(writes)}   writes(mov to table): {len(writes)}")
print()
for k, ins in writes:
    print(f"--- WRITE at {ins.address:#010x} ---")
    for m in range(max(0, k - 6), min(k + 3, len(insns))):
        mark = "  <<< WRITE" if m == k else ""
        print(f"  {insns[m].address:#010x}  {insns[m].mnemonic:6s} {insns[m].op_str}{mark}")
    print()
