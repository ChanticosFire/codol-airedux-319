"""Disassemble 0x5C05F0 (the connect state machine) looking for the 4->0 timeout.

Round 83 quantified the mismatch: the client needs 4.55 s to react to state=3, but
only waits 0.84 s in state 4.  So somewhere in here a counter/timer decides to
give up.  Look for writes to the state global, decrements, and comparisons
against small constants.
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


def cstr(va, n=40):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


start = 0x5C05F0
off = start - text_va
print(f"=== {start:#x} first 0x100 bytes ===")
for ins in md.disasm(code[off:off + 0x100], start):
    mark = ""
    if "0x76446b0" in ins.op_str:
        mark = "  <<< NET STATE"
    elif ins.mnemonic in ("dec", "inc") and "dword ptr [" in ins.op_str and "+" in ins.op_str:
        mark = "  <-- counter"
    elif ins.mnemonic == "cmp" and ("0x76446" in ins.op_str or "+0x" in ins.op_str):
        mark = "  <-- compare"
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

print()
print("=== all writes that could touch the state global in .text ===")
#  mov dword ptr [reg + disp], imm/reg   where disp contains 0x446b0-ish patterns
import re
pat = re.compile(rb"\x89[\x80-\xbf].{2}\xb0\x46\x64\x07", re.S)  # mov [reg+0x76446b0], reg
hits = [m.start() for m in pat.finditer(code)]
print(f"  indexed store candidates: {len(hits)} -> {[hex(text_va + h) for h in hits[:5]]}")
pat2 = re.compile(rb"\xc7[\x80-\xbf].{2}\xb0\x46\x64\x07", re.S)  # mov [reg+0x76446b0], imm
hits2 = [m.start() for m in pat2.finditer(code)]
print(f"  indexed store-imm candidates: {len(hits2)} -> {[hex(text_va + h) for h in hits2[:5]]}")
