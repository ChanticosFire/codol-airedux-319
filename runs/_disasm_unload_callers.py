import pefile
import capstone

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
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


for start, label in ((0x7EF180, "unload caller A"), (0x7EF2E0, "unload caller B")):
    off = start - (base + t.VirtualAddress)
    print(f"=== {label} {hex(start)} (calls 0x7F2600 unload) ===")
    for ins in md.disasm(code[off:off + 0x80], start):
        mark = ""
        if ins.mnemonic == "call":
            if ins.op_str == "0x7f2600":
                mark = "  <<< CALLS UNLOAD"
            else:
                mark = "  <-- call"
        elif "0x76446b0" in ins.op_str:
            mark = "  <<< net_state"
        elif "0x84aba50" in ins.op_str:
            mark = "  <<< ui_state"
        elif ins.mnemonic in ("push", "mov", "lea", "cmp") and "0xdb" in ins.op_str:
            for token in ins.op_str.split(","):
                token = token.strip()
                if token.startswith("0xdb"):
                    try:
                        s = cstr(int(token, 16))
                    except Exception:
                        s = None
                    if s:
                        mark = f"  <-- {s!r}"
        print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
    print()

# enclosing functions of both call sites
print("=== enclosing entries ===")
for hit in (0x7EF1AE, 0x7EF31B):
    entry = None
    for cand in range(hit, hit - 0x500, -1):
        o = cand - (base + t.VirtualAddress)
        if o < 0:
            break
        if code[o:o + 3] == b"\x55\x8b\xec":
            entry = cand
            break
    print(f"  call {hit:#x} -> entry {entry if entry is None else hex(entry)}")
