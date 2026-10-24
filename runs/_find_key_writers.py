"""Find every instruction that writes to [reg+0x109260..0x109274].

These six dwords are the "connection identity" keys that CLpacketEvent compares
against the incoming packet.  They read as zero on our client, so the comparison
always fails and every netchan packet is dropped.

Looking for the writers tells us who is supposed to populate them.
"""
import pefile
import capstone
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

OFFSETS = [0x109260, 0x109264, 0x109268, 0x10926C, 0x109270, 0x109274]
patterns = [(struct.pack("<I", off), off) for off in OFFSETS]

print("=== raw occurrences of each displacement in .text ===")
for needle, off in patterns:
    hits = []
    pos = 0
    while True:
        i = code.find(needle, pos)
        if i < 0:
            break
        hits.append(text_va + i)
        pos = i + 1
    print(f"  {off:#08x}: {len(hits)} hits -> {[hex(h) for h in hits[:8]]}")

print()
print("=== disassemble around each hit (looking for a store) ===")
seen = set()
for needle, off in patterns:
    pos = 0
    while True:
        i = code.find(needle, pos)
        if i < 0:
            break
        # instruction likely starts 2-7 bytes before the displacement
        for back in range(2, 9):
            start = i - back
            if start < 0:
                continue
            for ins in md.disasm(code[start:start + 12], text_va + start):
                if ins.address + ins.size <= text_va + i:
                    continue
                if ins.address in seen:
                    break
                if off is not None and f"{off:#x}" in ins.op_str.lower():
                    seen.add(ins.address)
                    kind = "STORE" if ins.mnemonic == "mov" and ins.op_str.split(",")[0].strip().startswith("[") else ""
                    if kind:
                        ctx = d[t.PointerToRawData + (ins.address - text_va) - 8:
                                t.PointerToRawData + (ins.address - text_va) + 16]
                        print(f"  {ins.address:#010x} {ins.mnemonic} {ins.op_str}"
                              f"   [{kind}]  ctx={ctx.hex(' ')}")
                break
        pos = i + 1
