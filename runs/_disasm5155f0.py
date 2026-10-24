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


start = 0x5155F0
off = start - (base + t.VirtualAddress)
print("=== 0x5155F0 .. 0x5156A0 (before the map-load call) ===")
for ins in md.disasm(code[off:off + 0xC0], start):
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
    elif ins.mnemonic.startswith("j") and "0x5156cd" in ins.op_str:
        mark = "  <<< jumps to SKIP label"
    print(hex(ins.address), ins.mnemonic, ins.op_str, ins.bytes.hex(" "), mark)
