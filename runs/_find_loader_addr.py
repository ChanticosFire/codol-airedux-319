"""Find code that takes the ADDRESS of 0x8536F60 (lea/push imm32).

Round 55 found zero direct *stores* to this pointer, and Round 58 proved 0x7F5E40
is not its creator.  A constructor would typically pass the object address to
something (`lea reg,[0x8536F60]` then `call`, or `push 0x8536F60`), so search
those encodings instead.
"""
import pefile
import capstone
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
ADDR = 0x8536F60

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
needle = struct.pack("<I", ADDR)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

sites = []
pos = 0
while True:
    i = code.find(needle, pos)
    if i < 0:
        break
    sites.append(text_va + i)
    pos = i + 1
print(f"imm32 occurrences: {len(sites)}")

print()
print("=== disassemble the instruction that owns each occurrence ===")
seen = set()
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
            if ins.address in seen:
                break
            seen.add(ins.address)
            tag = ""
            if ins.mnemonic == "lea":
                tag = "  <-- ADDRESS TAKEN (lea)"
            elif ins.mnemonic == "push":
                tag = "  <-- ADDRESS PUSHED"
            print(f"  {ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str:38s}"
                  f" bytes={ins.bytes.hex(' ')}{tag}")
            break

print()
print("=== callers of the enclosing function for each lea/push ===")
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
            if ins.mnemonic not in ("lea", "push"):
                break
            o = ins.address - text_va
            entry = None
            for cand in range(o, max(o - 0x600, 0), -1):
                if code[cand:cand + 3] == b"\x55\x8b\xec":
                    entry = text_va + cand
                    break
            if entry:
                # who calls that entry?
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
                print(f"  {ins.mnemonic} at {ins.address:#x} -> func {entry:#x}, "
                      f"callers={len(hits)} {[hex(x) for x in hits[:5]]}")
            break
