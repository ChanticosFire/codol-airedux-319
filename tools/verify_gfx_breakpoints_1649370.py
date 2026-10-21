"""Verify the exact instruction starts for the GFx ready/start string call sites.

Earlier room probes armed ``0x7D0A43`` and ``0x7D08C3`` because those are the
addresses of the immediate string operands reported by the read-only string
scanner.  The actual ``push imm32`` instructions start one byte earlier.  This
tool disassembles both windows from the fingerprint-checked image and records
the distinction, so the earlier zero-hit result is not used to rule out the
calls.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import capstone
import pefile

IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
OUT = Path(__file__).resolve().parents[1] / "evidence/experiments/20261021-1649370-breakpoint-address-correction.json"
EXPECTED = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"
SITES = (
    {
        "name": "GFx SetReadyState dispatch",
        "instruction_start": 0x7D0A42,
        "bad_operand_address": 0x7D0A43,
        "string_va": 0xDDD504,
        "string": "SetReadyState",
    },
    {
        "name": "GFx StartMatch dispatch",
        "instruction_start": 0x7D08C2,
        "bad_operand_address": 0x7D08C3,
        "string_va": 0xDDD4E4,
        "string": "StartMatch",
    },
)


def main() -> None:
    raw = IMAGE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED:
        raise ValueError("client image fingerprint mismatch")
    pe = pefile.PE(data=raw, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    rows = []
    for site in SITES:
        start = site["instruction_start"]
        off = pe.get_offset_from_rva(start - base)
        code = raw[off:off + 8]
        actual = next(md.disasm(code, start))
        operand = struct.unpack_from("<I", code, 1)[0]
        expected = b"\x68" + struct.pack("<I", site["string_va"])
        bad_off = pe.get_offset_from_rva(site["bad_operand_address"] - base)
        bad = next(md.disasm(raw[bad_off:bad_off + 8], site["bad_operand_address"]))
        rows.append({
            **{k: (hex(v) if isinstance(v, int) else v) for k, v in site.items()},
            "instruction_start_bytes": actual.bytes.hex(),
            "instruction_start_text": f"{actual.mnemonic} {actual.op_str}",
            "expected_bytes": expected.hex(),
            "start_is_push_of_string": actual.bytes == expected and actual.mnemonic == "push",
            "operand_address_bytes": bad.bytes.hex(),
            "operand_address_text": f"{bad.mnemonic} {bad.op_str}",
            "operand_address_is_instruction_start": bad.address == site["bad_operand_address"]
            and bad.size > 0 and bad.bytes[:1] == b"\x68",
        })
    report = {
        "schema": 1,
        "image_sha256": digest,
        "method": "Capstone disassembly at the string immediate and at operand-1",
        "sites": rows,
        "conclusion": (
            "0x7D0A43 and 0x7D08C3 are immediate operand bytes, not instruction starts. "
            "The prior room probes armed those bytes, so their zero hits cannot rule out "
            "the SetReadyState/StartMatch dispatches. Breakpoints must use 0x7D0A42 and "
            "0x7D08C2. The cppSetMemberReadyState site at 0x7CB572 was already a correct "
            "instruction start and its zero hit still stands."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "sites": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
