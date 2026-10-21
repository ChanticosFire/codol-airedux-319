"""Read-only native references for the ABC CFunctionContainer.SetReadyState lead."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import capstone
import pefile

IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
EXPECTED = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"
TERMS = ("SetReadyState", "CFunctionContainer")
WINDOW_START = 0x7D0A00
WINDOW_END = 0x7D0A90


def scan(raw: bytes) -> dict:
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError("Build 1649370 image mismatch")
    pe = pefile.PE(data=raw, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    code = [s for s in pe.sections if s.Characteristics & 0x20000000]
    matches = []
    for term in TERMS:
        needle = term.encode("ascii") + b"\0"
        start = 0
        while (offset := raw.find(needle, start)) >= 0:
            start = offset + 1
            va = base + pe.get_rva_from_offset(offset)
            packed = struct.pack("<I", va)
            refs = []
            for section in code:
                chunk = section.get_data()
                at = chunk.find(packed)
                while at >= 0:
                    refs.append(hex(base + section.VirtualAddress + at))
                    at = chunk.find(packed, at + 1)
            matches.append({"term": term, "file_offset": hex(offset), "string_va": hex(va),
                            "direct_operand_refs": refs})
    engine = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    window = raw[pe.get_offset_from_rva(WINDOW_START - base):pe.get_offset_from_rva(WINDOW_END - base)]
    instructions = [{"va": hex(i.address), "bytes": i.bytes.hex(),
                     "mnemonic": i.mnemonic, "operands": i.op_str}
                    for i in engine.disasm(window, WINDOW_START)]
    return {"schema": 1, "image_sha256": EXPECTED,
            "method": "exact null-terminated strings, direct absolute operand search, Capstone disassembly of bounded window",
            "matches": matches, "window": {"start": hex(WINDOW_START), "end": hex(WINDOW_END),
                                    "instructions": instructions},
            "limit": "Static references and disassembly; native callback direction and runtime execution require further verification."}


def main() -> None:
    result = scan(IMAGE.read_bytes())
    output = Path(__file__).resolve().parents[1] / "evidence/experiments/20261021-1649370-ready-native.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "matches": result["matches"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
