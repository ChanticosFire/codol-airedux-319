"""Read the 101-byte window 0x454A35..0x454A9A where the crash happens.

Round 109 bracketed the crash to this range; 0x454A35 is `cmp dword [0x827F738],0`
(the `table` global).  Print every instruction with its bytes so we can spot the
faulting access.
"""
import capstone
import pefile

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
LO, HI = 0x454A35, 0x454A9A + 0x20

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


off = LO - text_va
print(f"=== {LO:#x} .. {HI:#x} ===")
for ins in md.disasm(code[off:off + (HI - LO)], LO):
    mark = ""
    if ins.address < 0x454A9A:
        mark = ""
    else:
        mark = "   (past 3/4 point)"
    if "0x827f738" in ins.op_str:
        mark += "  <<< TABLE"
    elif "0x8536f60" in ins.op_str:
        mark += "  <<< loading object"
    elif "0x84aba50" in ins.op_str:
        mark += "  <<< ui_state"
    elif ins.mnemonic == "call":
        mark += "  <-- call"
    elif ins.mnemonic.startswith("ret"):
        mark += "  <<<< RET"
    elif ins.mnemonic in ("push", "mov", "lea", "cmp") and "0xdb" in ins.op_str:
        for tok in ins.op_str.split(","):
            tok = tok.strip()
            if tok.startswith("0xdb"):
                try:
                    s = cstr(int(tok, 16))
                except Exception:
                    s = None
                if s:
                    mark += f"  <-- {s!r}"
    print(f"{ins.address:#010x}  {ins.bytes.hex(' '):<22s} {ins.mnemonic:6s} {ins.op_str}{mark}")
