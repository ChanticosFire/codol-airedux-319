"""Search the client binary for the external addresses seen in netstat.

Round 68 found the client holding sockets to 42.187.183.162:8080 and 116.130.229.213:8000
plus four TCP connections. If those addresses are baked into the executable this finds the
exact RVA, which is where the configuration is read from.

    python tools/find_ip.py 42.187.183.162 116.130.229.213
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "runtime" / "client-1604220" / "codoMP_client_shipRetail.exe"


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


def off_to_rva(secs, off: int) -> int | None:
    for vaddr, vsize, rawptr, rawsize in secs:
        if rawptr <= off < rawptr + rawsize:
            return vaddr + (off - rawptr)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ips", nargs="+", help="dotted-quad addresses to look for")
    ap.add_argument("--exe", default=str(EXE))
    args = ap.parse_args()

    path = Path(args.exe)
    if not path.exists():
        print(f"not found: {path}")
        return 2
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    image_base = struct.unpack_from("<I", data, pe + 0x34)[0]
    secs = sections(data, pe)
    print(f"{path.name}  size={len(data)}  image_base={image_base:#x}")

    for ip in args.ips:
        parts = [int(p) for p in ip.split(".")]
        b = bytes(parts)
        hits: list[int] = []
        i = data.find(b)
        while i >= 0:
            hits.append(i)
            i = data.find(b, i + 1)
        print(f"\n{ip}  as {b.hex()}: {len(hits)} hit(s)")
        for off in hits[:8]:
            rva = off_to_rva(secs, off)
            if rva is not None:
                print(f"    file {off:#08x}  rva {rva:#08x}  va {image_base + rva:#010x}")
            else:
                print(f"    file {off:#08x}  (not in any section)")
        text_hits = []
        needle = ip.encode()
        j = data.find(needle)
        while j >= 0:
            text_hits.append(j)
            j = data.find(needle, j + 1)
        print(f"  ascii form: {len(text_hits)} hit(s)")
        for off in text_hits[:8]:
            rva = off_to_rva(secs, off)
            if rva is not None:
                print(f"    file {off:#08x}  rva {rva:#08x}  va {image_base + rva:#010x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
