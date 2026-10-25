"""Disassemble around 0x77C343 - the instruction that zeroes net_state.

This is the reset that makes CA_CONNECTING (4) collapse to 0 after ~0.84 s.
Find the enclosing function and the branch condition that reaches it.
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


def cstr(va, n=48):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


start = 0x77C2E0
off = start - text_va
print(f"=== {start:#x} .. (reset site 0x77C343) ===")
for ins in md.disasm(code[off:off + 0xB0], start):
    mark = ""
    if ins.address == 0x77C343:
        mark = "  <<<<< WRITES net_state = 0"
    elif "0x76446b0" in ins.op_str:
        mark = "  <<< net_state"
    elif ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic in ("push", "mov", "lea", "cmp", "test") and "0xdb" in ins.op_str:
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

# enclosing function
entry = None
for cand in range(0x77C343, 0x77C343 - 0x900, -1):
    o = cand - text_va
    if o < 0:
        break
    if code[o:o + 3] == b"\x55\x8b\xec":
        entry = cand
        break
print()
print(f"enclosing entry: {entry if entry is None else hex(entry)}")

if entry:
    import struct
    hits = []
    p2 = 0
    while True:
        j = code.find(b"\xe8", p2)
        if j < 0:
            break
        rel = struct.unpack_from("<i", code, j + 1)[0]
        if (text_va + j + 5 + rel) & 0xFFFFFFFF == entry:
            hits.append(text_va + j)
        p2 = j + 1
    print(f"callers of {entry:#x}: {len(hits)} -> {[hex(x) for x in hits[:8]]}")
