"""Search for client-state machine names and svc_clientEnter identifiers.

Round 230 disproved clc+0x10 == state.  To find the real "entered the game"
transition we look for the debug/state name table (CA_PRIMED, CA_ACTIVE, ...)
and for the protocol handler name (clientEnter / svc_clientEnter).
"""
import pefile
import struct

EXE = r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
d = open(EXE, "rb").read()


def va_of(off):
    for s in pe.sections:
        lo = s.PointerToRawData
        hi = lo + s.SizeOfRawData
        if lo <= off < hi:
            return base + s.VirtualAddress + (off - lo), s.Name.rstrip(b"\x00").decode("latin-1")
    return None, None


needles = [
    b"CA_PRIMED", b"CA_ACTIVE", b"CA_LOADING", b"CA_CONNECTED",
    b"CA_CHALLENGING", b"CA_CONNECTING", b"CA_DISCONNECTED",
    b"clientEnter", b"svc_clientEnter", b"client_enter",
    b"CL_ParseClientEnter", b"CL_ClientEnter",
]

for n in needles:
    hits = []
    p = 0
    while True:
        j = d.find(n, p)
        if j < 0:
            break
        hits.append(j)
        p = j + 1
        if len(hits) >= 4:
            break
    print("  %-22r hits=%d" % (n, len(hits)))
    for j in hits:
        va, sec = va_of(j)
        end = d.find(b"\x00", j)
        s = d[j:end]
        print("      %#010x (%s)  %r" % (va or 0, sec, s[:60]))

print()
print("=== references from .text for any hit we found ===")
text = None
for s in pe.sections:
    if s.Name.rstrip(b"\x00") == b".text":
        text = s
        break
tlo, thi = text.PointerToRawData, text.PointerToRawData + text.SizeOfRawData

for n in needles:
    p = 0
    while True:
        j = d.find(n, p)
        if j < 0:
            break
        p = j + 1
        va, sec = va_of(j)
        if va is None:
            continue
        imm = struct.pack("<I", va)
        q = 0
        refs = []
        while True:
            r = d.find(imm, q)
            if r < 0:
                break
            if tlo <= r < thi:
                refs.append(base + text.VirtualAddress + (r - tlo))
            q = r + 1
        if refs:
            print("  %-22r (VA %#x): refs %s" % (n, va, [hex(x) for x in refs[:6]]))
