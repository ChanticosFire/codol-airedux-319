"""Analyse 0x453760: what does it expect in [ebp+8]?

Round 100 proved the crash moves into this function once the two out-of-bounds
reads are neutralised, and we currently pass 0 for both of its stack arguments.
This script walks the function and reports every use of [ebp+8] / [ebp+0xC]
(and of the registers they are copied into), plus the allocation it performs.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x453760
SPAN = 0x300

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


def cstr(va, n=48):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


off = START - text_va
print(f"=== {START:#x} (first 0x{SPAN:x} bytes) ===")
arg_users = {}
n = 0
for ins in md.disasm(code[off:off + SPAN], START):
    mark = ""
    if "ebp + 8]" in ins.op_str:
        mark = "  <<< arg1 [ebp+8]"
    elif "ebp + 0xc]" in ins.op_str:
        mark = "  <<< arg2 [ebp+0xC]"
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
    if n > 110:
        print("  … (truncated)")
        break

print()
print("=== all reads of [ebp+8] / [ebp+0xC] in full span ===")
for ins in md.disasm(code[off:off + SPAN], START):
    if "ebp + 8]" in ins.op_str or "ebp + 0xc]" in ins.op_str:
        print(f"  {ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str}")
