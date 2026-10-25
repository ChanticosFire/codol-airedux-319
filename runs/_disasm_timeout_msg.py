"""Disassemble around 0x5C2589 - the EXE_ERR_SERVER_TIMEOUT report inside CLpacketEvent.

Round 88 captured Com_Error(2, "EXE_ERR_SERVER_TIMEOUT") when net_state dropped
4 -> 0.  This site is inside 0x5C2260 (CLpacketEvent), which we already know
discards packets when net_state is 0.  Print the comparison that reaches it.
"""
import capstone
import pefile

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


start = 0x5C24E0
off = start - text_va
print(f"=== {start:#x} .. 0x5C25B0  (timeout report at 0x5C2589) ===")
for ins in md.disasm(code[off:off + 0xD0], start):
    mark = ""
    if ins.address == 0x5C2589:
        mark = "  <<<<< pushes EXE_ERR_SERVER_TIMEOUT"
    elif "0x76446b0" in ins.op_str:
        mark = "  <<< net_state"
    elif ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic in ("cmp", "test"):
        mark = "  <-- compare"
    elif ins.mnemonic in ("push", "mov", "lea") and "0xdb" in ins.op_str:
        for tok in ins.op_str.split(","):
            tok = tok.strip()
            if tok.startswith("0xdb"):
                try:
                    s = cstr(int(tok, 16))
                except Exception:
                    s = None
                if s:
                    mark = f"  <-- {s!r}"
    print(f"{ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str}{mark}")

# what function are we in?
entry = None
for cand in range(0x5C2589, 0x5C2589 - 0x400, -1):
    o = cand - text_va
    if o < 0:
        break
    if code[o:o + 3] == b"\x55\x8b\xec":
        entry = cand
        break
print()
print(f"enclosing entry: {entry if entry is None else hex(entry)}  (CLpacketEvent is 0x5C2260)")
