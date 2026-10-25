"""Disassemble 0x49E600 (Com_LoadFastfiles) to find its exits.

Round 95 showed the client loads 11 fastfiles (last one common_gametype_mp),
sets table=1, then crashes 0.12 s later without ever opening
mp_crash_tropical.ff.  If 0x49E600 returns, the crash is in its caller;
if it never returns, the crash is inside it.
"""
import capstone
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
START = 0x49E600
SPAN = 0x300

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


def cstr(va, n=52):
    off = va_of(va)
    if off is None:
        return None
    raw = d[off:off + n]
    e = raw.find(b"\x00")
    return raw[:e] if 0 < e <= n else raw


off = START - text_va
chunk = code[off:off + SPAN]
rets = []
calls = []
print(f"=== {START:#x} .. {START+SPAN:#x} ===")
for ins in md.disasm(chunk, START):
    mark = ""
    if ins.mnemonic.startswith("ret"):
        rets.append(ins.address)
        mark = "  <<<< RET"
    elif ins.mnemonic == "call":
        calls.append((ins.address, ins.op_str))
        mark = "  <-- call"
    elif "0x76446b0" in ins.op_str:
        mark = "  <<< net_state"
    elif "0x827f738" in ins.op_str:
        mark = "  <<< table"
    elif "0x1c2b6cc" in ins.op_str:
        mark = "  <<< gate"
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
    if mark or ins.mnemonic in ("ret", "retn"):
        print(f"{ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str}{mark}")

print()
print(f"RET sites in this span: {[hex(x) for x in rets]}")
print(f"calls: {len(calls)}")
for a, o in calls:
    print(f"  {a:#010x}  call {o}")
