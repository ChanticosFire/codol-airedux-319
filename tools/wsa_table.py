"""Decode the WSA error jump table used by 0xBB15E0.

At 0xBB1661 the code does:

    movzx ecx, byte ptr [ecx + 0xBB1768]     ; index table, 62 bytes
    jmp dword ptr [ecx*4 + 0xBB1750]         ; address table

Since the index table begins only 0x18 bytes after the address table, the address table can
hold at most six entries - so the 62 WSA error codes collapse onto six handlers. This dumps
both tables from the on-disk image and reports which handler each code selects.

    python tools/wsa_table.py
"""
from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "runtime" / "client-1604220" / "codoMP_client_shipRetail.exe"

# These are virtual addresses as written in the code (image base 0x400000),
# so they must be rebased before being looked up as RVAs.
ADDR_TABLE_VA = 0xBB1750
IDX_TABLE_VA = 0xBB1768
N_ADDR = (IDX_TABLE_VA - ADDR_TABLE_VA) // 4      # 6
N_IDX = 62
WSA_BASE = 0x2714                           # 10004

WSA_NAMES = {
    10004: "WSAEINTR", 10009: "WSAEBADF", 10013: "WSAEACCES", 10014: "WSAEFAULT",
    10022: "WSAEINVAL", 10024: "WSAEMFILE", 10035: "WSAEWOULDBLOCK",
    10036: "WSAEINPROGRESS", 10037: "WSAEALREADY", 10038: "WSAENOTSOCK",
    10039: "WSAEDESTADDRREQ", 10040: "WSAEMSGSIZE", 10041: "WSAEPROTOTYPE",
    10042: "WSAENOPROTOOPT", 10043: "WSAEPROTONOSUPPORT", 10044: "WSAESOCKTNOSUPPORT",
    10045: "WSAEOPNOTSUPP", 10046: "WSAEPFNOSUPPORT", 10047: "WSAEAFNOSUPPORT",
    10048: "WSAEADDRINUSE", 10049: "WSAEADDRNOTAVAIL", 10050: "WSAENETDOWN",
    10051: "WSAENETUNREACH", 10052: "WSAENETRESET", 10053: "WSAECONNABORTED",
    10054: "WSAECONNRESET", 10055: "WSAENOBUFS", 10056: "WSAEISCONN",
    10057: "WSAENOTCONN", 10058: "WSAESHUTDOWN", 10060: "WSAETIMEDOUT",
    10061: "WSAECONNREFUSED", 10064: "WSAEHOSTDOWN", 10065: "WSAEHOSTUNREACH",
}


def sections(data: bytes, pe: int) -> list[tuple[int, int, int, int]]:
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    soh = struct.unpack_from("<H", data, pe + 20)[0]
    base = pe + 24 + soh
    out = []
    for i in range(nsec):
        o = base + i * 40
        vsize, vaddr = struct.unpack_from("<II", data, o + 8)
        rawsize, rawptr = struct.unpack_from("<II", data, o + 16)
        out.append((vaddr, vsize, rawptr, rawsize))
    return out


def rva_to_off(secs, rva: int) -> int | None:
    for vaddr, vsize, rawptr, rawsize in secs:
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr)
    return None


def main() -> int:
    data = EXE.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    image_base = struct.unpack_from("<I", data, pe + 0x34)[0]
    secs = sections(data, pe)
    print(f"{EXE.name}  image_base={image_base:#x}")

    ADDR_TABLE = ADDR_TABLE_VA - image_base
    IDX_TABLE = IDX_TABLE_VA - image_base
    off = rva_to_off(secs, ADDR_TABLE)
    if off is None:
        print(f"address table RVA {ADDR_TABLE:#x} not found")
        return 2
    addrs = struct.unpack_from(f"<{N_ADDR}I", data, off)
    print(f"\naddress table at {ADDR_TABLE:#x} ({N_ADDR} entries):")
    for i, a in enumerate(addrs):
        print(f"  [{i}] {image_base + a:#010x}   (rva {a:#x})")

    off = rva_to_off(secs, IDX_TABLE)
    if off is None:
        print(f"index table RVA {IDX_TABLE:#x} not found")
        return 2
    idx = data[off:off + N_IDX]
    print(f"\nindex table at {IDX_TABLE:#x} ({N_IDX} bytes):")
    buckets: dict[int, list[int]] = {}
    for i, sel in enumerate(idx):
        buckets.setdefault(sel, []).append(WSA_BASE + i)
    for sel in sorted(buckets):
        codes = buckets[sel]
        names = ", ".join(WSA_NAMES.get(c, str(c)) for c in codes)
        handler = image_base + addrs[sel] if sel < len(addrs) else None
        print(f"  index {sel} -> {handler:#010x} : {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
