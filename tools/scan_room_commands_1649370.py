"""Resolve the native callbacks registered for ``room.startgame`` and ``room.leave``.

The command registration block at ``0x63A0F0`` builds command nodes.  It loads
the command name into ESI and then writes the callback with
``mov dword ptr [node+8], imm32``.  Earlier notes treated ``0x639890`` as the
startgame handler, but it is the leave handler.  This read-only tool decodes the
two verified registration sites and records the exact mapping.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pefile

IMAGE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
OUT = Path(__file__).resolve().parents[1] / "evidence/experiments/20261021-1649370-room-command-callbacks.json"
EXPECTED = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"
# (command, name_load_va, callback_store_va). Both sites are inside the verified
# registration block and use mov esi, imm32 / mov dword ptr [imm32], imm32.
SITES = (
    ("room.leave", 0x63A10D, 0x63A12C),
    ("room.startgame", 0x63A13C, 0x63A15B),
)


def main() -> None:
    raw = IMAGE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED:
        raise ValueError("client image fingerprint mismatch")
    pe = pefile.PE(data=raw, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase

    def bytes_at(va: int, count: int) -> bytes:
        return pe.get_data(va - base, count)

    def cstring(va: int) -> str:
        off = pe.get_offset_from_rva(va - base)
        return raw[off:raw.index(b"\0", off)].decode("ascii")

    rows = []
    for expected_name, name_va, store_va in SITES:
        name_code = bytes_at(name_va, 5)
        store_code = bytes_at(store_va, 10)
        if name_code[0] != 0xBE or store_code[0] != 0xC7 or store_code[1] != 0x05:
            raise ValueError(f"registration instruction mismatch at {name_va:#x}/{store_va:#x}")
        string_va = struct.unpack("<I", name_code[1:5])[0]
        node_field = struct.unpack("<I", store_code[2:6])[0]
        callback = struct.unpack("<I", store_code[6:10])[0]
        name = cstring(string_va)
        rows.append({
            "command": name,
            "name_load_va": hex(name_va),
            "name_code_hex": name_code.hex(),
            "string_va": hex(string_va),
            "callback_store_va": hex(store_va),
            "callback_store_hex": store_code.hex(),
            "node_callback_field": hex(node_field),
            "callback_va": hex(callback),
            "callback_entry_hex": bytes_at(callback, 16).hex(),
            "name_matches": name == expected_name,
        })
    report = {
        "schema": 1,
        "image_sha256": digest,
        "method": "decode the two verified command registration writes",
        "commands": rows,
        "correction": (
            "room.startgame -> 0x6398A0; room.leave -> 0x639890. "
            "0x639890 is a leave dispatch through the room vtable +0x38, not the startgame handler. "
            "The startgame callback selects parameters from global index [0x3306910] and calls "
            "the current room vtable +0x3C."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
