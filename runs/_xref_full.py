"""Complete control-flow reference scan: call (E8), jmp (E9), jcc (0F 8x).

Round 33 wrongly declared 0x5C241C dead code because only E8 was scanned.
This tool checks all four encodings so that mistake cannot repeat.
"""
import pefile
import struct
import sys

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress


def refs_to(target):
    out = {"call": [], "jmp": [], "jcc": []}
    for i in range(len(code) - 6):
        b = code[i]
        if b == 0xE8:                       # call rel32
            rel = struct.unpack_from("<i", code, i + 1)[0]
            if (text_va + i + 5 + rel) & 0xFFFFFFFF == target:
                out["call"].append(text_va + i)
        elif b == 0xE9:                     # jmp rel32
            rel = struct.unpack_from("<i", code, i + 1)[0]
            if (text_va + i + 5 + rel) & 0xFFFFFFFF == target:
                out["jmp"].append(text_va + i)
        elif b == 0x0F and code[i + 1] & 0xF0 == 0x80:   # jcc rel32
            rel = struct.unpack_from("<i", code, i + 2)[0]
            if (text_va + i + 6 + rel) & 0xFFFFFFFF == target:
                out["jcc"].append(text_va + i)
    return out


targets = [int(x, 0) for x in sys.argv[1:]] or [0x5AA980, 0x5C241C, 0x473A50, 0x5C2434]
for target in targets:
    r = refs_to(target)
    total = sum(len(v) for v in r.values())
    print(f"{target:#010x}: total={total}  "
          f"call={len(r['call'])} {[hex(x) for x in r['call'][:5]]}  "
          f"jmp={len(r['jmp'])} {[hex(x) for x in r['jmp'][:5]]}  "
          f"jcc={len(r['jcc'])} {[hex(x) for x in r['jcc'][:5]]}")
