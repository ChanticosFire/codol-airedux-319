"""Locate the code that promotes clc.state to CA_ACTIVE (6).

Observed: clc+0x10 == 5 (CA_PRIMED).  The client never reaches CA_ACTIVE(6), so
the player never spawns.  COD4's clientConnection_t begins with `int state`, and
this build's state lives at +0x10, so the promotion is a store of 6 into
[reg+0x10] for whichever register holds clc.

Search the whole .text for `mov dword ptr [reg+0x10], 6` encodings
(C7 40/41/42/43/45/46/47 10 06 00 00 00) and report each hit with context.
"""
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()

text = None
for s in pe.sections:
    if s.Name.rstrip(b"\x00") == b".text":
        text = s
        break
code = d[text.PointerToRawData:text.PointerToRawData + text.SizeOfRawData]
text_va = base + text.VirtualAddress

# mov dword ptr [reg+0x10], 6   ->  C7 <modrm> 10 06 00 00 00
patterns = {}
for modrm in (0x40, 0x41, 0x42, 0x43, 0x45, 0x46, 0x47):
    pat = bytes([0xC7, modrm, 0x10, 0x06, 0x00, 0x00, 0x00])
    patterns[modrm] = pat

regnames = {0x40: "eax", 0x41: "ecx", 0x42: "edx",
            0x43: "ebx", 0x45: "ebp", 0x46: "esi", 0x47: "edi"}

hits = []
for modrm, pat in patterns.items():
    p = 0
    while True:
        j = code.find(pat, p)
        if j < 0:
            break
        hits.append((text_va + j, regnames[modrm]))
        p = j + 1

print("  hits for 'mov dword [reg+0x10], 6' : %d" % len(hits))
for va, reg in sorted(hits):
    print("    %#010x   mov dword ptr [%s+0x10], 6" % (va, reg))

# Also look for the compare side:  cmp dword [reg+0x10], 5  ->  83 78/79/7A/7B/7D/7E/7F 10 05
print()
print("  hits for 'cmp dword [reg+0x10], 5' :")
ct = 0
for modrm in (0x78, 0x79, 0x7A, 0x7B, 0x7D, 0x7E, 0x7F):
    pat = bytes([0x83, modrm, 0x10, 0x05])
    p = 0
    while True:
        j = code.find(pat, p)
        if j < 0:
            break
        va = text_va + j
        # nearest preceding hit tells us who else touches +0x10
        print("    %#010x   cmp dword ptr [%s+0x10], 5"
              % (va, {0x78: "eax", 0x79: "ecx", 0x7A: "edx", 0x7B: "ebx",
                      0x7D: "ebp", 0x7E: "esi", 0x7F: "edi"}[modrm]))
        ct += 1
        p = j + 1
        if ct > 24:
            break
print("  total cmp hits:", ct)
