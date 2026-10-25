"""Disassemble 0x5C0776 - the CA_CONNECTING (state 4) branch of 0x5C05F0.

Round 84 showed the timeout path (0x5C0F1B) only returns without touching
net_state, so the 4->0 reset must happen somewhere else.  This branch sends
`connect`; look for the state write and any failure path that resets it.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def va_of(va):
    for s in pe.sections:
        if s.VirtualAddress + base <= va < s.VirtualAddress + base + s.Misc_VirtualSize:
            return s.PointerToRawData + (va - base - s.VirtualAddress)
    return None


def cstr(va, n=44):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


start = 0x5C0776
off = start - text_va
print(f"=== {start:#x}  state=4 branch (sends connect) ===")
n = 0
for ins in md.disasm(code[off:off + 0x140], start):
    mark = ""
    if "0x76446b0" in ins.op_str:
        head = ins.op_str.split(",")[0].strip()
        if ins.mnemonic == "mov" and head.startswith("["):
            mark = "  <<<<< WRITES NET STATE"
        else:
            mark = "  <<< reads net_state"
    elif ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic in ("push", "mov", "lea") and "0xdb" in ins.op_str:
        for tok in ins.op_str.split(","):
            tok = tok.strip()
            if tok.startswith("0xdb"):
                try:
                    s = cstr(int(tok, 16))
                except Exception:
                    s = None
                if s:
                    mark = f"  <-- {s!r}"
    print(f"{ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str}{mark}")
    n += 1
    if n > 70:
        break

print()
print("=== every instruction in .text that writes [0x76446B0] ===")
# mov dword ptr [0x76446b0], imm32  = C7 05 B0 46 64 07 xx xx xx xx
import re
hits = []
for m in re.finditer(rb"\xc7\x05\xb0\x46\x64\x07", code):
    v = int.from_bytes(code[m.start() + 6:m.start() + 10], "little")
    hits.append((text_va + m.start(), f"mov dword [0x76446B0], {v:#x}"))
for m in re.finditer(rb"\x89\x0d\xb0\x46\x64\x07", code):
    hits.append((text_va + m.start(), "mov dword [0x76446B0], ecx"))
for m in re.finditer(rb"\x89\x15\xb0\x46\x64\x07", code):
    hits.append((text_va + m.start(), "mov dword [0x76446B0], edx"))
for m in re.finditer(rb"\x89\x05\xb0\x46\x64\x07", code):
    hits.append((text_va + m.start(), "mov dword [0x76446B0], eax"))
for m in re.finditer(rb"\x89\x1d\xb0\x46\x64\x07", code):
    hits.append((text_va + m.start(), "mov dword [0x76446B0], ebx"))
print(f"  absolute stores: {len(hits)}")
for a, txt in sorted(hits):
    print(f"    {a:#010x}  {txt}")
