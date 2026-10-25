"""Disassemble 0x59B560 — the function whose FIRST call crashes.

Round 113: 0x454A54 `call 0x59B560` is invoked exactly once (loop=1) before the
client dies, so the fault is inside it.  It takes one stack argument (`push 1`).
Print its prologue and flag the first memory accesses / calls.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x59B560
SPAN = 0x200

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
    if ins.mnemonic == "call":
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
    elif ins.mnemonic.startswith("ret"):
        mark = "  <<<< RET"
    print(f"{ins.address:#010x}  {ins.bytes.hex(' '):<20s} {ins.mnemonic:6s} {ins.op_str}{mark}")
    n += 1
    if n > 80 or ins.mnemonic.startswith("ret"):
        break
