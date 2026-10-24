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


def cstr(va, n=44):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


for start, label in ((0x674EB0, "netchan process A"), (0x674740, "netchan process B")):
    off = start - (base + t.VirtualAddress)
    print(f"=== {label} {hex(start)} ===")
    for ins in md.disasm(code[off:off + 0x70], start):
        mark = ""
        if ins.mnemonic == "call":
            mark = "  <-- call"
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
        elif ins.mnemonic == "ret":
            mark = "  <<< RETURN"
        print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
    print()

# who calls 0x674740
import struct
text_va = base + t.VirtualAddress
for target in (0x674740,):
    hits = []
    pos = 0
    while True:
        i = code.find(b"\xe8", pos)
        if i < 0:
            break
        rel = struct.unpack("<i", code[i + 1:i + 5])[0]
        if (text_va + i + 5 + rel) & 0xFFFFFFFF == target:
            hits.append(text_va + i)
        pos = i + 1
    print(f"call {target:#x}: {len(hits)} -> {[hex(h) for h in hits[:8]]}")
