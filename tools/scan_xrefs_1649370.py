"""Find absolute-address xrefs inside a 1649370 image (static, read-only).

All static claims in this repository must say which image they came from.  The
shipped image is `bin\\v1649370\\codol1649370-offline.exe`; the runtime copy in
`workspaces\\offline-runs\\r107flow\\runtime` differs by 31 bytes (see
`tools/compare_image_bytes_1649370.py`), so this tool defaults to the shipped
image and prints its digest.

    python tools/scan_xrefs_1649370.py 0x1c166e8 0x1988b50
    python tools/scan_xrefs_1649370.py 0x1c166e8 --image <path> --max 50
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import capstone
import pefile

DEFAULT_IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")


def sections(image: Path):
    pe = pefile.PE(str(image), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    out = []
    for section in pe.sections:
        out.append({
            "name": section.Name.decode(errors="replace").rstrip("\0"),
            "va": base + section.VirtualAddress,
            "vsize": section.Misc_VirtualSize,
            "raw": section.PointerToRawData,
            "rawsize": section.SizeOfRawData,
        })
    return base, out


def code_blob(data: bytes, secs, name: str):
    for section in secs:
        if section["name"] == name:
            start = section["raw"]
            return data[start:start + section["rawsize"]], section["va"]
    raise SystemExit(f"no section named {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", type=lambda text: int(text, 0))
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--section", default=".text")
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--disp", action="store_true",
                    help="match any memory operand displacement (structure field "
                         "offsets such as ps+0x494), not only absolute addresses")
    ap.add_argument("--context", type=int, default=0,
                    help="also disassemble this many bytes before the xref")
    args = ap.parse_args()

    data = args.image.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    base, secs = sections(args.image)
    blob, va = code_blob(data, secs, args.section)
    print(f"image={args.image}")
    print(f"sha256={digest}")
    print(f"section={args.section} va={va:#x} raw={len(blob)}")

    wanted = {}
    for target in args.targets:
        wanted.setdefault(target & 0xFFFFFFFF, []).append(target)

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    md.skipdata = True
    hits: dict[int, list[tuple[int, str, str, str]]] = {t: [] for t in wanted}
    total = 0
    for insn in md.disasm(blob, va):
        total += 1
        if insn.id == 0:  # skipdata pseudo-instruction
            continue
        try:
            operands = insn.operands
        except capstone.CsError:
            continue
        for op in operands:
            address = None
            kind = None
            if op.type == capstone.x86.X86_OP_IMM:
                address = op.imm & 0xFFFFFFFF
                kind = "imm"
            elif op.type == capstone.x86.X86_OP_MEM:
                if op.mem.base == 0 and op.mem.index == 0:
                    address = op.mem.disp & 0xFFFFFFFF
                    kind = "mem"
                elif args.disp:
                    address = op.mem.disp & 0xFFFFFFFF
                    kind = "disp"
            if address is not None and address in hits:
                hits[address].append((insn.address, kind, insn.mnemonic, insn.op_str))
    print(f"instructions={total}")
    for target, rows in hits.items():
        print(f"\n== {target:#x} : {len(rows)} xref(s)")
        for address, kind, mnemonic, ops in rows[: args.max]:
            print(f"  {address:#010x}  {mnemonic} {ops}   [{kind}]")
        if len(rows) > args.max:
            print(f"  ... {len(rows) - args.max} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
