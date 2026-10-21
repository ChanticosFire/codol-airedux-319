"""Read-only PE xrefs for native room start and GFx room methods."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pefile

IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
OUT = Path(__file__).resolve().parents[1] / "evidence/experiments/20261021-1649370-room-start-refs.json"
EXPECTED = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"
TERMS = ("room.startgame", "StartMatch", "StartMatchCountDown", "SetReadyState",
         "mmstart sv_resetServer; 2486 %d;")


def main() -> None:
    raw = IMAGE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED:
        raise ValueError("client image fingerprint mismatch")
    pe = pefile.PE(data=raw, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    code_sections = [s for s in pe.sections if s.Characteristics & 0x20000000]
    rows = []
    for term in TERMS:
        needle = term.encode("ascii")
        start = 0
        while (offset := raw.find(needle, start)) >= 0:
            start = offset + 1
            if term != TERMS[-1] and raw[offset + len(needle):offset + len(needle) + 1] != b"\0":
                continue
            rva = pe.get_rva_from_offset(offset)
            string_va = base + rva
            refs = []
            packed = struct.pack("<I", string_va)
            for section in code_sections:
                code = section.get_data()
                at = code.find(packed)
                while at >= 0:
                    ref = base + section.VirtualAddress + at
                    refs.append({"operand_va": hex(ref), "preceding_opcode": hex(code[at - 1]),
                                 "context_hex": code[max(0, at - 12):at + 20].hex()})
                    at = code.find(packed, at + 1)
            rows.append({"term": term, "file_offset": hex(offset), "string_va": hex(string_va),
                         "executable_operand_refs": refs})
    report = {"schema": 1, "image": str(IMAGE), "sha256": digest,
              "method": "exact ASCII strings and direct 32-bit VA operand references",
              "matches": rows,
              "interpretation": {
                  "room_start_handler": "0x639890 reads room pointer [0x82e13fc] and jumps through vtable slot +0x38; runtime target unknown",
                  "room_start_register_candidate": "0x63a13c uses room.startgame pointer before call 0x4f37a0",
                  "map_command_builder": "0x632462 references mmstart/sv_resetServer/.../map %s format string",
                  "limitation": "Static references do not establish runtime execution or a playable match"
              }}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "matches": len(rows),
                      "refs": sum(len(x["executable_operand_refs"]) for x in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
