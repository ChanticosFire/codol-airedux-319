"""Complete control-flow reference scan v2.

Round 33 missed jcc; Round 35's first pass missed *short* jcc/jmp too.
This version covers all six encodings:
  E8 call rel32, E9 jmp rel32, EB jmp rel8,
  0F 8x jcc rel32, 7x jcc rel8
An address is only "dead" if every one of these yields zero.
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
    out = {"call": [], "jmp32": [], "jmp8": [], "jcc32": [], "jcc8": []}
    n = len(code)
    for i in range(n - 6):
        b = code[i]
        if b == 0xE8:
            rel = struct.unpack_from("<i", code, i + 1)[0]
            if (text_va + i + 5 + rel) & 0xFFFFFFFF == target:
                out["call"].append(text_va + i)
        elif b == 0xE9:
            rel = struct.unpack_from("<i", code, i + 1)[0]
            if (text_va + i + 5 + rel) & 0xFFFFFFFF == target:
                out["jmp32"].append(text_va + i)
        elif b == 0xEB:
            rel = struct.unpack_from("<b", code, i + 1)[0]
            if (text_va + i + 2 + rel) & 0xFFFFFFFF == target:
                out["jmp8"].append(text_va + i)
        elif b == 0x0F and (code[i + 1] & 0xF0) == 0x80:
            rel = struct.unpack_from("<i", code, i + 2)[0]
            if (text_va + i + 6 + rel) & 0xFFFFFFFF == target:
                out["jcc32"].append(text_va + i)
        elif 0x70 <= b <= 0x7F:
            rel = struct.unpack_from("<b", code, i + 1)[0]
            if (text_va + i + 2 + rel) & 0xFFFFFFFF == target:
                out["jcc8"].append(text_va + i)
    return out


targets = [int(x, 0) for x in sys.argv[1:]] or [0x5AA980, 0x5C241C, 0x473A50, 0x5C2434]
for target in targets:
    r = refs_to(target)
    total = sum(len(v) for v in r.values())
    parts = " ".join(f"{k}={len(v)}{[hex(x) for x in v[:4]]}" for k, v in r.items() if v)
    print(f"{target:#010x}: total={total}  {parts if parts else 'NO REFERENCES'}")
