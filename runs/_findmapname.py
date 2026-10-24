import pefile
import re
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()

text = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
text_va = base + text.VirtualAddress


def va_of(off):
    for s in pe.sections:
        if s.PointerToRawData <= off < s.PointerToRawData + s.SizeOfRawData:
            return base + s.VirtualAddress + (off - s.PointerToRawData)
    return None


# 1) locate candidate configstring key strings
targets = {}
for pat in (rb"mapname\x00", rb"sv_mapname\x00", rb"g_gametype\x00"):
    for m in re.finditer(pat, d):
        va = va_of(m.start())
        if va is None:
            continue
        targets.setdefault(va, pat.rstrip(b"\x00").decode())
        if len(targets) > 12:
            break

print("candidate key strings:")
for va, name in sorted(targets.items())[:12]:
    print(f"  {va:#010x}  {name}")

# 2) find code references (lea reg,[imm32] and push imm32)
print()
for va, name in sorted(targets.items())[:12]:
    pat = struct.pack("<I", va)
    hits = []
    pos = 0
    while True:
        i = code.find(pat, pos)
        if i < 0:
            break
        hits.append(text_va + i)
        pos = i + 1
    if hits:
        print(f"{name!r} @ {va:#x}: {len(hits)} refs -> {[hex(h) for h in hits[:6]]}")
