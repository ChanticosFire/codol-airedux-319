"""Find every instruction that WRITES net_state (0x76446B0).

Prior rounds only scanned reads (`cmp dword ptr [0x76446b0], N`).  The state is
being reset to 0 by the client's own state machine, so the writers are what
matter now.

Two forms to look for:
  * absolute:  mov dword ptr [0x76446B0], imm32   (C7 05 ..)
               mov dword ptr [0x76446B0], reg     (89 0D/15/1D/05/..)
  * indexed:   mov dword ptr [reg*32 + 0x76446B0], ...  (displacement present)
"""
import pefile
import capstone
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
ADDR = 0x76446B0

pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()
t = [s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text"][0]
code = d[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
text_va = base + t.VirtualAddress
needle = struct.pack("<I", ADDR)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

print("=== all imm32 occurrences of 0x76446B0 ===")
sites = []
pos = 0
while True:
    i = code.find(needle, pos)
    if i < 0:
        break
    sites.append(text_va + i)
    pos = i + 1
print(f"  {len(sites)} sites")

print()
print("=== classify each site (store vs load) ===")
stores = []
loads = []
seen = set()
for site in sites:
    # instruction starts 1..7 bytes before the displacement
    for back in range(1, 8):
        start = site - back
        if start < 0:
            continue
        for ins in md.disasm(code[start:start + 12], text_va + start):
            if ins.address + ins.size <= site:
                continue
            if ins.address in seen:
                break
            if f"{ADDR:#x}" not in ins.op_str.lower():
                break
            seen.add(ins.address)
            is_store = ins.mnemonic in ("mov", "or", "and", "xor", "inc", "dec") and \
                ins.op_str.split(",")[0].strip().startswith("[")
            ctx = code[max(0, ins.address - text_va - 6):
                       ins.address - text_va + 14]
            rec = (ins.address, ins.mnemonic, ins.op_str, ins.bytes.hex(" "), ctx.hex(" "))
            if is_store:
                stores.append(rec)
            else:
                loads.append(rec)
            break

print(f"  STORES: {len(stores)}")
for a, m, o, b, c in stores:
    print(f"    {a:#010x}  {m} {o}")
    print(f"        bytes={b}")
    print(f"        ctx  ={c}")
print(f"  LOADS (first 6 of {len(loads)}):")
for a, m, o, b, c in loads[:6]:
    print(f"    {a:#010x}  {m} {o}")
