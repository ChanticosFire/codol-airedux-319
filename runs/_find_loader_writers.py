"""Find writers of the loading-object pointer at 0x8536F60.

Round 57 proved this pointer stays 0 while 0x49E600 runs, which crashes the
client right after CA_PRIMED.  Locating its writers tells us who is supposed to
create the object (and whether that code ever runs).

NOTE: `code` holds raw .text bytes, so VAs must be converted with
`off = va - text_va`.
"""
import pefile
import capstone
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
ADDR = 0x8536F60

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
needle = struct.pack("<I", ADDR)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

sites = []
pos = 0
while True:
    i = code.find(needle, pos)
    if i < 0:
        break
    sites.append(text_va + i)
    pos = i + 1
print(f"sites (imm32 occurrences): {len(sites)}")

stores, loads = [], []
seen = set()
for site in sites:
    site_off = site - text_va
    for back in range(1, 8):
        start_off = site_off - back
        if start_off < 0:
            continue
        start_va = text_va + start_off
        for ins in md.disasm(code[start_off:start_off + 12], start_va):
            if not (ins.address <= site < ins.address + ins.size):
                continue
            if ins.address in seen:
                break
            if f"{ADDR:#x}" not in ins.op_str.lower():
                break
            seen.add(ins.address)
            head = ins.op_str.split(",")[0].strip()
            is_store = ins.mnemonic in ("mov", "or", "and", "xor", "inc", "dec") \
                and head.startswith("[")
            rec = (ins.address, ins.mnemonic, ins.op_str, ins.bytes.hex(" "))
            (stores if is_store else loads).append(rec)
            break

print(f"STORES: {len(stores)}")
for a, m, o, b in stores:
    print(f"  {a:#010x}  {m} {o}   bytes={b}")
print(f"LOADS: {len(loads)} (first 8)")
for a, m, o, b in loads[:8]:
    print(f"  {a:#010x}  {m} {o}")

# Who calls the function containing each store?
print()
print("=== enclosing functions of the stores ===")
for a, m, o, b in stores:
    off = a - text_va
    entry = None
    for cand in range(off, max(off - 0x600, 0), -1):
        if code[cand:cand + 3] == b"\x55\x8b\xec":
            entry = text_va + cand
            break
    print(f"  store {a:#010x} -> entry ~{entry if entry is None else hex(entry)}")
