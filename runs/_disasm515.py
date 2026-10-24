import pefile
import capstone

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

MAPNAME = 0xDB0DA4
start = 0x515400
off = start - (base + t.VirtualAddress)
print("=== 0x515400 .. 0x515600 ===")
for ins in md.disasm(code[off:off + 0x200], start):
    mark = ""
    if ins.mnemonic == "call" and ins.op_str.startswith("0x4"):
        mark = "  <-- call cl/loader"
    if ins.mnemonic in ("push", "lea") and "0xdb0da4" in ins.op_str:
        mark = '  <-- "mapname"'
    print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
