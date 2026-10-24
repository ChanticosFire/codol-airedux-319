import pefile
import capstone

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
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


hit = 0x5AAB40
back = None
for cand in range(hit, hit - 0x400, -1):
    o = cand - (base + t.VirtualAddress)
    if o < 0:
        break
    if code[o:o + 3] == b"\x55\x8b\xec":
        back = cand
        break
print("=== enclosing entry:", hex(back) if back else "unknown", "===")
if back:
    o = back - (base + t.VirtualAddress)
    for ins in md.disasm(code[o:o + 0x110], back):
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
        if ins.address == hit:
            mark += "   <<< calls CL_ParseServerMessage"
        print(hex(ins.address), ins.mnemonic, ins.op_str, mark)
