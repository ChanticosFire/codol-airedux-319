"""Read-only, bounded PE string-reference triage for candidate game commands."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pefile

IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
OUTPUT = Path(__file__).resolve().parents[1] / "evidence/experiments/20261021-1649370-command-refs.json"
TERMS = ("devmap", "map_restart", "botsAddAll", "botClassTable")


def main() -> None:
    raw = IMAGE.read_bytes()
    pe = pefile.PE(data=raw, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = [s for s in pe.sections if s.SizeOfRawData]
    executable = [s for s in sections if s.Characteristics & 0x20000000]
    rows = []
    for term in TERMS:
        for suffix in (b"\0",):
            needle = term.encode("ascii") + suffix
            for section in sections:
                data = section.get_data()
                offset = data.find(needle)
                while offset >= 0:
                    string_va = base + section.VirtualAddress + offset
                    refs = []
                    address_bytes = struct.pack("<I", string_va)
                    for code_section in executable:
                        code = code_section.get_data()
                        at = code.find(address_bytes)
                        while at >= 0:
                            ref_va = base + code_section.VirtualAddress + at
                            refs.append({"operand_va": hex(ref_va),
                                         "preceding_opcode": hex(code[at - 1]) if at else None,
                                         "context_hex": code[max(0, at - 12):at + 20].hex()})
                            at = code.find(address_bytes, at + 1)
                    rows.append({"term": term, "string_va": hex(string_va),
                                 "section": section.Name.rstrip(b"\0").decode("ascii", "replace"),
                                 "executable_operand_refs": refs})
                    offset = data.find(needle, offset + 1)
    report = {"schema": 1, "image": str(IMAGE), "sha256": hashlib.sha256(raw).hexdigest(),
              "method": "exact ASCII NUL string and 32-bit VA operand search; candidate refs, not registration proof",
              "matches": rows}
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "matches": len(rows),
                      "refs": sum(len(x["executable_operand_refs"]) for x in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
