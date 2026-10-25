"""Disassemble the loop body around 0x453850 to find its counter and exit test.

Round 102 measured 0x453850 hit 19 times before the crash, so there is a loop
of ~19 iterations.  Locate its induction variable and the bounds check.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x4537D0
SPAN = 0x1A0

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


off = START - text_va
print(f"=== {START:#x} .. {START+SPAN:#x} ===")
for ins in md.disasm(code[off:off + SPAN], START):
    mark = ""
    if ins.mnemonic in ("inc", "dec", "add", "sub") and ("ebp -" in ins.op_str or "ebp-" in ins.op_str):
        mark = "  <-- counter?"
    elif ins.mnemonic in ("cmp", "jmp") or ins.mnemonic.startswith("j"):
        mark = "  <-- control"
    elif ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic.startswith("ret"):
        mark = "  <<<< RET"
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
