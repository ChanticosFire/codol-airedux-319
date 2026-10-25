"""Find safe hook points at ~1/4, 1/2, 3/4 of the 0x453AD8..0x455485 range.

The range is 6573 bytes, so three probes can cut it to ~1640 bytes in one run.
A point is "safe" if a valid instruction starts exactly there with size >= 5 and
it is not a branch target boundary problem (we only need >=5 bytes of complete
instructions for hook_any to relocate).

Usage: python runs/_find_bisect_points.py
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
LO, HI = 0x453AD8, 0x455485

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

# Linear sweep from LO so we know real instruction boundaries.
off = LO - text_va
insns = list(md.disasm(code[off:off + (HI - LO) + 0x40], LO))
print(f"range {LO:#x}..{HI:#x} = {HI-LO} bytes, {len(insns)} instructions")

boundaries = {}
for i in insns:
    boundaries[i.address] = i

def find_point(target, max_back=0x80):
    """Walk forward from `target` until an instruction with size>=5 begins."""
    for addr in range(target, target + max_back):
        ins = boundaries.get(addr)
        if ins and ins.size >= 5 and not ins.mnemonic.startswith(("j", "ret", "call")):
            return ins
    return None

span = HI - LO
for label, frac in (("1/4", 0.25), ("1/2", 0.5), ("3/4", 0.75)):
    target = LO + int(span * frac)
    ins = find_point(target)
    if ins:
        print(f"  {label}: target={target:#x} -> hook {ins.address:#x} "
              f"({ins.mnemonic} {ins.op_str}, size={ins.size})")
    else:
        print(f"  {label}: target={target:#x} -> no safe point found")
