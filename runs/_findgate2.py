import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress


def callers(target):
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
    return hits


for target, label in ((0x49E600, "Com_Init-ish gate writer"),
                      (0x4FE740, "Com_LoadFastfiles wrapper"),
                      (0x49E160, "Com_LoadFastfiles")):
    hits = callers(target)
    print(f"call {target:#x} ({label}): {len(hits)} -> {[hex(h) for h in hits[:10]]}")

# who writes 0x1CDAF1C
ADDR = 0x1CDAF1C
le = struct.pack("<I", ADDR)
refs = []
pos = 0
while True:
    i = code.find(le, pos)
    if i < 0:
        break
    refs.append(text_va + i)
    pos = i + 1
print(f"\nimm32 refs to 0x1CDAF1C: {len(refs)}")
for r in refs[:10]:
    ctx = d[t.PointerToRawData + (r - text_va) - 4:
            t.PointerToRawData + (r - text_va) + 8]
    print(f"   {r:#010x}  ctx={ctx.hex(' ')}")
