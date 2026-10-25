"""Find the code that reports EXE_ERR_SERVER_TIMEOUT (string at 0xDBB658).

Round 88 captured Com_Error(2, "EXE_ERR_SERVER_TIMEOUT") right after net went
4 -> 0.  The 3000 ms throttle found in 0x5C05F0 cannot be the trigger (net only
stayed in 4 for ~0.85 s), so locate every instruction that references this
string and print the comparison that guards it.
"""
import capstone
import pefile
import re
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
STR_VA = 0xDBB658
TEXT = b"EXE_ERR_SERVER_TIMEOUT"

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

# 1) verify the string really is at STR_VA
for s in pe.sections:
    lo = s.VirtualAddress + base
    hi = lo + s.Misc_VirtualSize
    if lo <= STR_VA < hi:
        off = s.PointerToRawData + (STR_VA - lo)
        raw = d[off:off + len(TEXT) + 2]
        print(f"string @ {STR_VA:#x} -> {raw!r}")
        break

# 2) all references (push imm32 / mov reg,imm32 / lea reg,[imm32])
needle = struct.pack("<I", STR_VA)
print()
print(f"=== imm32 occurrences of {STR_VA:#x} ===")
sites = [text_va + m.start() for m in re.finditer(re.escape(needle), code)]
print(f"  {len(sites)} sites: {[hex(x) for x in sites]}")

print()
print("=== disassemble each referencing instruction ===")
for site in sites:
    site_off = site - text_va
    for back in range(1, 8):
        start_off = site_off - back
        if start_off < 0:
            continue
        start_va = text_va + start_off
        for ins in md.disasm(code[start_off:start_off + 12], start_va):
            if not (ins.address <= site < ins.address + ins.size):
                continue
            print(f"  {ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str}")
            break
        else:
            continue
        break
