"""Find writers/references of 0xC7341DB -- the flag that skips connection-key init."""
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
ADDR = 0xC7341DB

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress

print("=== section containing the flag ===")
for s in pe.sections:
    lo = base + s.VirtualAddress
    hi = lo + s.Misc_VirtualSize
    if lo <= ADDR < hi:
        print(f"  {s.Name.rstrip(b'\\x00').decode()}  {lo:#x} - {hi:#x}  "
              f"({hi - lo:#x} bytes)")

print()
print("=== imm32 references in .text ===")
needle = struct.pack("<I", ADDR)
hits = []
pos = 0
while True:
    i = code.find(needle, pos)
    if i < 0:
        break
    hits.append(text_va + i)
    pos = i + 1
print(f"  {len(hits)} hits")
for h in hits[:16]:
    off = h - text_va
    ctx = code[max(0, off - 6):off + 10]
    print(f"  {h:#010x}  ctx={ctx.hex(' ')}")

print()
print("=== byte-sized store patterns (mov byte [addr], imm8) ===")
for imm, label in ((0x01, "1 (skip it)"), (0x00, "0 (allow init)")):
    pat = bytes([0xC6, 0x05]) + needle + bytes([imm])
    found = []
    pos = 0
    while True:
        i = code.find(pat, pos)
        if i < 0:
            break
        found.append(text_va + i)
        pos = i + 1
    print(f"  mov byte [flag], {label}: {len(found)} -> {[hex(x) for x in found[:8]]}")
