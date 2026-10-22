"""Inventory static absolute references to 1649370 Auth/LSG globals.

This scans PE executable sections only. Results are static candidates, not
proof that a branch ran or that a value was written at runtime.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import capstone
import pefile
from capstone.x86 import X86_OP_MEM

TARGETS = (0x84ABB08, 0x84ABB0C, 0x84ABB14, 0x84ABA7C)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    pe = pefile.PE(str(args.image), fast_load=True)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    md.skipdata = True
    rows = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        start = pe.OPTIONAL_HEADER.ImageBase + section.VirtualAddress
        code = section.get_data()
        for ins in md.disasm(code, start):
            if ins.id == 0:
                continue
            hits = [target for target in TARGETS if any(
                operand.type == X86_OP_MEM and operand.mem.base == 0
                and operand.mem.index == 0 and operand.mem.disp == target
                for operand in ins.operands)]
            if not hits:
                continue
            first = ins.operands[0]
            writes = (first.type == X86_OP_MEM and first.mem.base == 0
                      and first.mem.index == 0 and first.mem.disp in hits
                      and ins.mnemonic not in ("cmp", "test", "push"))
            rows.append({"va": hex(ins.address), "bytes": ins.bytes.hex(),
                         "assembly": f"{ins.mnemonic} {ins.op_str}",
                         "targets": [hex(v) for v in hits],
                         "write_candidate": writes,
                         "section": section.Name.rstrip(b"\0").decode("ascii", "replace")})
    result = {"schema": 1, "image": str(args.image),
              "image_sha256": __import__("hashlib").sha256(args.image.read_bytes()).hexdigest(),
              "coverage": "linear disassembly of PE executable sections; packed or runtime generated code excluded",
              "references": rows}
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    writes = [r for r in rows if r["write_candidate"]]
    print(json.dumps({"references": len(rows), "write_candidates": writes},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
