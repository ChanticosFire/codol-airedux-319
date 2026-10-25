"""Show the exact bytes at the timeout guard 0x5C252D..0x5C2532.

Round 89/90 established this is `cmp ebx,9; jl 0x5C2589` where ebx = net_state.
The plan is to NOP the `jl` so the EXE_ERR_SERVER_TIMEOUT branch is never taken.
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

start = 0x5C252D
off = start - text_va
print("raw bytes at", hex(start), ":", code[off:off + 10].hex(" "))
print()
for ins in md.disasm(code[off:off + 10], start):
    print(f"  {ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str:22s} bytes={ins.bytes.hex(' ')}")
    if ins.mnemonic.startswith("j"):
        break

print()
print("=== plan ===")
print("  0x5C2530 : 78 57 (jl +0x57)  ->  90 90 (nop nop)")
print("  effect   : never take the EXE_ERR_SERVER_TIMEOUT branch")
