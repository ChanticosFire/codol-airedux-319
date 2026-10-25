"""Disassemble the tail of 0x453760 (after the two init loops) up to its ret.

Round 104 proved both loops (19 + 18 items) complete normally, so the crash is in
the epilogue.  Find the second loop's back-edge, then print everything after it
until the function returns.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x453760
SEARCH = 0x1400

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
insns = list(md.disasm(code[off:off + SEARCH], START))

# find all rets
rets = [i.address for i in insns if i.mnemonic.startswith("ret")]
print(f"RET sites in {START:#x}..+0x{SEARCH:x}: {[hex(x) for x in rets]}")

# find the second loop's back-edge: a jne/jmp targeting 0x4539A0
backs = []
for i in insns:
    if i.mnemonic.startswith("j") and i.op_str.strip() == "0x4539a0":
        backs.append(i.address)
print(f"back-edges to 0x4539A0: {[hex(x) for x in backs]}")

# print from the back-edge onward until the ret
if backs:
    start_tail = backs[-1] - 0x10
    print()
    print(f"=== tail from {start_tail:#x} to the ret ===")
    printing = False
    for i in insns:
        if i.address < start_tail:
            continue
        mark = ""
        if i.mnemonic.startswith("ret"):
            mark = "  <<<< RET"
        elif i.mnemonic == "call":
            mark = "  <-- call"
        elif "ebp - 0xd4" in i.op_str:
            mark = "  <<< loop counter"
        elif i.mnemonic in ("push", "mov", "lea") and "0xdb" in i.op_str:
            for tok in i.op_str.split(","):
                tok = tok.strip()
                if tok.startswith("0xdb"):
                    try:
                        s = cstr(int(tok, 16))
                    except Exception:
                        s = None
                    if s:
                        mark = f"  <-- {s!r}"
        print(f"{i.address:#010x}  {i.mnemonic:6s} {i.op_str}{mark}")
        if i.mnemonic.startswith("ret"):
            break
