"""Collect bounded Build 1649370 mode-name clues without inferring reachability."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


EXPECTED_EXE = "36997674B18F2896DE5E9D755686F6922AF10708F355175714058D0A0172B537"
NEEDLES = (
    "coop_train_mp_firingrange", "coop_training_mp_cargoship",
    "CPP_TryLaunchTutorialMap", "cppOpenTrainEOGMenu",
    "scr_gameended", "botsAddAll", "CoD4Host",
)


def sections(image: bytes) -> tuple[int, list[tuple[int, int, int]]]:
    if image[:2] != b"MZ":
        raise ValueError("not PE/MZ")
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    if image[pe:pe + 4] != b"PE\0\0":
        raise ValueError("missing PE signature")
    count = struct.unpack_from("<H", image, pe + 6)[0]
    optional_size = struct.unpack_from("<H", image, pe + 20)[0]
    image_base = struct.unpack_from("<I", image, pe + 24 + 28)[0]
    table = pe + 24 + optional_size
    result = []
    for i in range(count):
        row = table + 40 * i
        raw_size, raw_offset = struct.unpack_from("<II", image, row + 16)
        virtual_address = struct.unpack_from("<I", image, row + 12)[0]
        result.append((raw_offset, raw_offset + raw_size, virtual_address))
    return image_base, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    exe = args.client / "codoMP_client_shipRetail.exe"
    image = exe.read_bytes()
    digest = hashlib.sha256(image).hexdigest().upper()
    if digest != EXPECTED_EXE:
        parser.error("EXE identity mismatch")
    image_base, rows = sections(image)
    strings = {}
    for name in NEEDLES:
        needle = name.encode("ascii")
        matches = []
        start = 0
        while (offset := image.find(needle, start)) != -1:
            mapped = [base + offset - begin for begin, end, base in rows if begin <= offset < end]
            rva = mapped[0] if len(mapped) == 1 else None
            pointer = struct.pack("<I", image_base + rva) if rva is not None else None
            xrefs = []
            if pointer is not None:
                pos = 0
                while (pos := image.find(pointer, pos)) != -1:
                    mapped_ref = [base + pos - begin for begin, end, base in rows if begin <= pos < end]
                    xrefs.append({"file_offset": pos, "rva": mapped_ref[0] if len(mapped_ref) == 1 else None})
                    pos += 1
            matches.append({"file_offset": offset, "rva": rva, "absolute_pointer_occurrences": xrefs})
            start = offset + 1
        strings[name] = matches
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    if (inventory.get("mismatches") or inventory.get("only_local") or inventory.get("only_archive")
            or inventory.get("files", {}).get("codoMP_client_shipRetail.exe", {}).get("sha256") != EXPECTED_EXE):
        parser.error("inventory is incomplete or does not match Build 1649370 EXE")
    files = inventory["files"]
    resource_groups = {}
    for key in ("coop_train_mp_firingrange", "coop_training_mp_cargoship"):
        resource_groups[key] = [
            {"relative_path": path, **meta}
            for path, meta in files.items()
            if path.lower().endswith(".ifs") and key in path.lower()
        ]
    report = {
        "schema_version": 1,
        "build": 1649370,
        "exe_sha256": digest,
        "evidence_type": "file-backed strings and resource filenames only",
        "strings": strings,
        "resource_groups": resource_groups,
        "limitations": ["No call-chain or runtime reachability established", "IFS filename is not proof of engine load or complete mode"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"strings": {k: len(v) for k, v in strings.items()},
                      "resource_groups": {k: len(v) for k, v in resource_groups.items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
