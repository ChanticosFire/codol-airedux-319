"""Find every instruction that WRITES net_state (0x76446B0).

Prior rounds only scanned reads.  The state is being reset to 0 by the client's
own state machine, so the writers matter now.

NOTE on addressing: `code` is the raw .text bytes, so any VA must be converted via
`off = va - text_va`.  (The first version of this script used the VA directly as
a list index and classified nothing.)
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

sites = []
pos = 0
while True:
    i = code.find(needle, pos)
    if i < 0:
        break
    sites.append(text_va + i)          # VA of the displacement bytes
    pos = i + 1
print(f"sites (imm32 occurrences): {len(sites)}")

stores = []
loads = []
seen = set()
for site in sites:
    site_off = site - text_va
    for back in range(1, 8):
        start_off = site_off - back
        if start_off < 0:
            continue
        start_va = text_va + start_off
        for ins in md.disasm(code[start_off:start_off + 12], start_va):
            # the instruction must actually cover the displacement bytes
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
print(f"LOADS: {len(loads)} (showing first 5)")
for a, m, o, b in loads[:5]:
    print(f"  {a:#010x}  {m} {o}")
