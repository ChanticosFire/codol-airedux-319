import pefile
import capstone

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

start = 0x514E70
off = start - (base + t.VirtualAddress)
print("=== 0x514E70 (systeminfo core) ===")
for ins in md.disasm(code[off:off + 0x180], start):
    mark = ""
    if ins.mnemonic == "call":
        mark = "  <-- call"
    if ins.mnemonic == "push" and ins.op_str.startswith("0xdb"):
        mark = "  <-- str"
    print(hex(ins.address), ins.mnemonic, ins.op_str, mark)

print()
start2 = 0x515130
off2 = start2 - (base + t.VirtualAddress)
print("=== 0x515130 (second handler) ===")
for ins in md.disasm(code[off2:off2 + 0xE0], start2):
    mark = ""
    if ins.mnemonic == "call":
        mark = "  <-- call"
    if ins.mnemonic == "push" and ins.op_str.startswith("0xdb"):
        mark = "  <-- str"
    print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
