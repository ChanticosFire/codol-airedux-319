"""Disassemble 0x42F2F0 — the function whose call never returns.

Drill path so far:
    0x453760 -> loop body 0x59B560 -> 0x42F3E0 -> **0x42F2F0**
Round 129: 0x42F2F0 entry hit once; 0x42F424 and the 0x42F48C exit both unreached.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x42F2F0
SPAN = 0x120

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

off = START - text_va
print(f"=== {START:#x} ===")
n = 0
for ins in md.disasm(code[off:off + SPAN], START):
    mark = ""
    op = ins.op_str
    if ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic.startswith("ret"):
        mark = "  <<<< RET"
    elif "]" in op and ins.mnemonic != "lea":
        mark = "  [mem]"
    if ins.mnemonic in ("push", "mov", "lea", "cmp") and "0xdb" in op:
        for tok in op.split(","):
            tok = tok.strip()
            if tok.startswith("0xdb"):
                hit = None
                for s2 in pe.sections:
                    lo = s2.VirtualAddress + base
                    hi = lo + s2.Misc_VirtualSize
                    if lo <= int(tok, 16) < hi:
                        o2 = s2.PointerToRawData + (int(tok, 16) - lo)
                        raw = d[o2:o2 + 44]
                        e = raw.find(b"\x00")
                        hit = raw[:e] if 0 < e <= 44 else raw
                        break
                if hit:
                    mark += f"  <-- {hit!r}"
    print(f"{ins.address:#010x}  {ins.bytes.hex(' '):<22s} {ins.mnemonic:6s} {op}{mark}")
    n += 1
    if ins.mnemonic.startswith("ret"):
        break
