"""Find write sites into the 0x1988B50 table using byte hits + local decode.

Round 143 proved whole-.text linear decode is unreliable (8.8 MB with data/padding).
This uses the verified approach: find the 4-byte little-endian operand 50 8B 98 01,
then decode only a few instructions backwards from the hit to classify read vs write.

    89 <modrm> ...   -> mov r/m32, r32   (WRITE)
    8B <modrm> ...   -> mov r32, r/m32   (READ)
"""
import capstone
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
TABLE = 0x1988B50
NEEDLE = struct.pack("<I", TABLE)          # 50 8b 98 01

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

hits = []
p = 0
while True:
    j = code.find(NEEDLE, p)
    if j < 0:
        break
    hits.append(j)
    p = j + 1
print(f"byte hits: {len(hits)}")
print()

writes = []
reads = 0
unknown = 0
for j in hits:
    # The table immediate occupies bytes [j, j+4).  Look back up to 8 bytes for
    # the start of a mov instruction whose displacement is this immediate.
    start = max(0, j - 8)
    seg = code[start:j + 4]
    best = None
    for ins in md.disasm(seg, text_va + start):
        # instruction must END exactly at j+4
        if ins.address + ins.size == text_va + j + 4:
            best = ins
    if best is None:
        unknown += 1
        continue
    b0 = best.bytes[0]
    if b0 == 0x89:
        writes.append((text_va + j, best))
    elif b0 == 0x8B:
        reads += 1
    else:
        unknown += 1

print(f"classified: writes={len(writes)} reads={reads} unknown={unknown}")
print()
for addr, ins in writes:
    print(f"--- WRITE  {ins.address:#010x}  {ins.bytes.hex(' ')}  {ins.mnemonic} {ins.op_str}")
