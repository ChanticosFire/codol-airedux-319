"""Locate the real configstring array by scanning process memory.

The buffer at 0xC87A48C turned out to be an app-level string table, not CoD's
cs.configstrings[].  CoD stores server info in configstring 0 as an InfoString
like "\\sv_hostname\\...\\mapname\\mp_crash_tropical\\...", so an InfoString
containing both "\\mapname\\" and the map name should exist wherever the real
array is.

Scans committed readable regions via VirtualQueryEx and reports every hit of
    b"\\mapname\\"
    b"mp_crash_tropical"
with its address, plus a 96-byte context dump for the first few hits.
"""
import ctypes
import struct
import sys

from ctypes import wintypes as W

pid = int(sys.argv[1])
NEEDLES = [b"\\mapname\\", b"mp_crash_tropical", b"\\sv_hostname\\"]
MAX_REPORT = 12

k = ctypes.WinDLL("kernel32")
k.OpenProcess.restype = W.HANDLE
h = k.OpenProcess(0x1F0FFF, False, pid)
if not h:
    raise SystemExit("OpenProcess failed")


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", W.DWORD), ("PartitionId", W.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", W.DWORD),
                ("Protect", W.DWORD), ("Type", W.DWORD)]


k.VirtualQueryEx.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
k.VirtualQueryEx.restype = ctypes.c_size_t

addr = 0
found = {n: [] for n in NEEDLES}
scanned = 0
while True:
    mbi = MBI()
    if not k.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        break
    base = mbi.BaseAddress or 0
    size = mbi.RegionSize
    addr = base + size
    if addr <= base:
        break
    # committed, readable, not guard
    if mbi.State != 0x1000:
        continue
    if mbi.Protect & 0x100:      # PAGE_GUARD
        continue
    if not (mbi.Protect & 0x02 or mbi.Protect & 0x04 or mbi.Protect & 0x20
            or mbi.Protect & 0x40 or mbi.Protect & 0x80):
        continue
    if size > 0x4000000:          # skip absurd regions
        continue
    pos = 0
    while pos < size:
        chunk = min(0x100000, size - pos)
        buf = ctypes.create_string_buffer(chunk)
        got = ctypes.c_size_t()
        if k.ReadProcessMemory(h, ctypes.c_void_p(base + pos), buf, chunk, ctypes.byref(got)):
            data = buf.raw[:got.value]
            scanned += got.value
            for n in NEEDLES:
                p = 0
                while True:
                    i = data.find(n, p)
                    if i < 0:
                        break
                    found[n].append(base + pos + i)
                    p = i + 1
        pos += chunk
    if base > 0x80000000:
        break

print("  scanned %.1f MB" % (scanned / 1048576.0))
for n in NEEDLES:
    hits = found[n]
    print()
    print("  %-20r hits: %d" % (n, len(hits)))
    for a in hits[:MAX_REPORT]:
        print("    %#010x" % a)
    if len(hits) > MAX_REPORT:
        print("    ... (%d more)" % (len(hits) - MAX_REPORT))

print()
print("  === context around first \\mapname\\ hit ===")
if found[b"\\mapname\\"]:
    a = found[b"\\mapname\\"][0] - 64
    buf = ctypes.create_string_buffer(256)
    got = ctypes.c_size_t()
    if k.ReadProcessMemory(h, ctypes.c_void_p(a), buf, 256, ctypes.byref(got)):
        d = buf.raw[:got.value]
        print("   base %#x:" % a)
        for i in range(0, len(d), 16):
            row = d[i:i + 16]
            print("     %#010x  %-47s %s" % (a + i, row.hex(" "),
                  "".join(chr(c) if 32 <= c < 127 else "." for c in row)))
