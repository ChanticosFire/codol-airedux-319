"""Find the caller of 0x49E600 (Com_LoadFastfiles) and show what runs right after.

Round 96 proved the function returns normally (entry=1, exit=1), so the crash
happens in whoever called it.  Locate the call site and disassemble the
instructions immediately following the call.
"""
import capstone
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
TARGET = 0x49E600

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


def cstr(va, n=52):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


hits = []
p = 0
while True:
    j = code.find(b"\xe8", p)
    if j < 0:
        break
    rel = struct.unpack_from("<i", code, j + 1)[0]
    if (text_va + j + 5 + rel) & 0xFFFFFFFF == TARGET:
        hits.append(text_va + j)
    p = j + 1

print(f"callers of {TARGET:#x}: {len(hits)} -> {[hex(x) for x in hits]}")

for site in hits:
    print()
    print(f"=== context around call site {site:#x} ===")
    start = site - 0x20
    off = start - text_va
    for ins in md.disasm(code[off:off + 0x60], start):
        mark = ""
        if ins.address == site:
            mark = "  <<<< CALL Com_LoadFastfiles"
        elif ins.mnemonic == "call":
            mark = "  <-- call"
        elif "0x827f738" in ins.op_str:
            mark = "  <<< table"
        elif "0x1c2b6cc" in ins.op_str:
            mark = "  <<< gate"
        elif "0x76446b0" in ins.op_str:
            mark = "  <<< net_state"
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

    # enclosing function entry
    entry = None
    for cand in range(site, site - 0x900, -1):
        o = cand - text_va
        if o < 0:
            break
        if code[o:o + 3] == b"\x55\x8b\xec":
            entry = cand
            break
    print(f"  enclosing entry: {entry if entry is None else hex(entry)}")
