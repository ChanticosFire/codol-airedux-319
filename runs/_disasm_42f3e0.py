"""Disassemble 0x42F3E0 (the name-lookup function whose call never returns).

Round 127: entry hit once (f42=1) but 0x454A71 never reached (a71=0) -> the fault
is inside this function.  Round 114 saw its prologue; print the whole thing with
emphasis on memory accesses and calls.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x42F3E0
SPAN = 0x140

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
    if ins.mnemonic in ("push", "mov", "lea") and "0xdb" in op:
        for tok in op.split(","):
            tok = tok.strip()
            if tok.startswith("0xdb"):
                try:
                    s = cstr(int(tok, 16))
                except Exception:
                    s = None
                if s:
                    mark += f"  <-- {s!r}"
    print(f"{ins.address:#010x}  {ins.bytes.hex(' '):<22s} {ins.mnemonic:6s} {op}{mark}")
    n += 1
    if ins.mnemonic.startswith("ret"):
        break
