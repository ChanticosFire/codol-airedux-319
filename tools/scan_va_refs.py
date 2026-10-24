"""Static scan: every instruction in the shipped image whose operand is a given VA."""
from __future__ import annotations

import sys

import capstone
import pefile

IMAGE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(IMAGE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
raw = open(IMAGE, "rb").read()
text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
code = raw[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
base_va = base + text.VirtualAddress

target = int(sys.argv[1], 0)
pattern = target.to_bytes(4, "little")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = False

hits = []
pos = code.find(pattern)
while pos >= 0:
    # disassemble a window that starts a few bytes before and includes the operand
    start = max(0, pos - 12)
    stop = min(len(code), pos + 8)
    for insn in md.disasm(code[start:stop], base_va + start):
        if insn.address <= base_va + pos < insn.address + insn.size:
            hits.append((insn.address, insn.mnemonic, insn.op_str))
    pos = code.find(pattern, pos + 1)

print(f"target {target:#x}: {len(hits)} instructions")
for addr, mnem, ops in hits:
    print(f"{addr:#010x}  {mnem} {ops}")
