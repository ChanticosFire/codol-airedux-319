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


def cstr(va, n=40):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


start = 0x515130
off = start - (base + t.VirtualAddress)
print("=== 0x515130 (mapname handler in CL_SystemInfoChanged) ===")
for ins in md.disasm(code[off:off + 0x110], start):
    mark = ""
    if ins.mnemonic == "call":
        mark = "  <-- call"
    if ins.mnemonic == "push" and ins.op_str.startswith("0xdb"):
        s = cstr(int(ins.op_str, 16))
        mark = f"  <-- {s!r}" if s else "  <-- str"
    print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
