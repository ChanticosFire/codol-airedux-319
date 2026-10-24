import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
text = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
text_va = base + text.VirtualAddress

# 1) callers of 0x484370
target = 0x484370
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
print(f"call 0x484370: {len(hits)} callers -> {[hex(h) for h in hits[:10]]}")

# 2) who writes 1 to 0x1C2B6CC
GATE = 0x1C2B6CC
addr_le = struct.pack("<I", GATE)
patterns = {
    "mov dword [gate],1   (C7 05 .. 01 00 00 00)": b"\xc7\x05" + addr_le + b"\x01\x00\x00\x00",
    "mov dword [gate],0   (C7 05 .. 00 00 00 00)": b"\xc7\x05" + addr_le + b"\x00\x00\x00\x00",
    "mov byte  [gate],1   (C6 05 .. 01)": b"\xc6\x05" + addr_le + b"\x01",
    "mov byte  [gate],0   (C6 05 .. 00)": b"\xc6\x05" + addr_le + b"\x00",
}
for name, pat in patterns.items():
    found = []
    pos = 0
    while True:
        i = code.find(pat, pos)
        if i < 0:
            break
        found.append(text_va + i)
        pos = i + 1
    print(f"{name}: {len(found)} -> {[hex(x) for x in found[:8]]}")

# 3) any reference to the gate address in .text (mov reg,imm / lea)
refs = []
pos = 0
while True:
    i = code.find(addr_le, pos)
    if i < 0:
        break
    refs.append(text_va + i)
    pos = i + 1
print(f"all imm32 references to 0x1C2B6CC in .text: {len(refs)}")
for r in refs[:12]:
    ctx = d[text.PointerToRawData + (r - text_va) - 3:
            text.PointerToRawData + (r - text_va) + 8]
    print(f"   {r:#010x}  ctx={ctx.hex(' ')}")
