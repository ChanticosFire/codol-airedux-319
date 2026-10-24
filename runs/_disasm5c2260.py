import pefile
import capstone
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def va_of(va):
    for s in pe.sections:
        if s.VirtualAddress + base <= va < s.VirtualAddress + base + s.Misc_VirtualSize:
            return s.PointerToRawData + (va - base - s.VirtualAddress)
    return None


def cstr(va, n=44):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


# 1) callers of CL_ParseServerMessage
for target, label in ((0x473A50, "CL_ParseServerMessage"),):
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
    print(f"call {target:#x} ({label}): {len(hits)} -> {[hex(h) for h in hits[:10]]}")

# 2) disassemble CLpacketEvent 0x5C2260
start = 0x5C2260
off = start - text_va
print()
print("=== CLpacketEvent 0x5C2260 ===")
for ins in md.disasm(code[off:off + 0x120], start):
    mark = ""
    if ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic in ("push", "mov", "lea", "cmp") and "0xdb" in ins.op_str:
        for token in ins.op_str.split(","):
            token = token.strip()
            if token.startswith("0xdb"):
                try:
                    s = cstr(int(token, 16))
                except Exception:
                    s = None
                if s:
                    mark = f"  <-- {s!r}"
    elif ins.mnemonic.startswith("j") and ins.op_str.startswith("0x5c2"):
        mark = "  <-- jump"
    print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
