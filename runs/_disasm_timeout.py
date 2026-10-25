"""Disassemble the timeout decision in 0x5C05F0 (after 0x5C0693).

Round 83 established the client waits only ~0.84 s in state 4 while needing 4.55 s
to react, so the give-up decision must be a time comparison.  0x5C0693 loads the
current timestamp into edx and 0x5C06A1 subtracts [conn+8] (the start time).
Print that region and decode the jump table at 0x5C0F2C.
"""
import capstone
import pefile
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


print("=== jump table at 0x5C0F2C (4 entries) ===")
off = 0x5C0F2C - text_va
for i in range(4):
    tgt = struct.unpack_from("<I", code, off + i * 4)[0]
    print(f"  [{i}] -> {tgt:#x}")

print()
print("=== 0x5C0693 .. 0x5C0760 (timeout logic) ===")
start = 0x5C0693
off = start - text_va
for ins in md.disasm(code[off:off + 0xD0], start):
    mark = ""
    if "0x76446b0" in ins.op_str:
        mark = "  <<< NET STATE"
    elif ins.mnemonic == "call":
        mark = "  <-- call"
    elif ins.mnemonic == "cmp" or ins.mnemonic == "test":
        mark = "  <-- test/cmp"
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
    elif ins.mnemonic == "mov" and "0x76446b0" in ins.op_str:
        mark = "  <<< WRITES NET STATE"
    print(f"{ins.address:#010x}  {ins.mnemonic:6s} {ins.op_str}{mark}")
