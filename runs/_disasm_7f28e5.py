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


start = 0x7F2870
off = start - (base + t.VirtualAddress)
print("=== 0x7F2870 region (loader object assignment at 0x7F28E5) ===")
for ins in md.disasm(code[off:off + 0x90], start):
    mark = ""
    if "0x8536f60" in ins.op_str:
        mark = "  <<< LOADER OBJECT"
    elif ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic == "ret":
        mark = "  <<< RETURN"
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

# find the enclosing function entry
print()
hit = 0x7F28E5
entry = None
for cand in range(hit, hit - 0x700, -1):
    o = cand - (base + t.VirtualAddress)
    if o < 0:
        break
    if code[o:o + 3] == b"\x55\x8b\xec":
        entry = cand
        break
print(f"enclosing entry: {entry if entry is None else hex(entry)}")

if entry is not None:
    import struct
    text_va = base + t.VirtualAddress
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
