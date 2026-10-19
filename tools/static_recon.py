#!/usr/bin/env python
"""Read-only static reconnaissance for the staged 1649370 client.

Produces a deterministic JSON summary of PE layout and of the TCLS / startup
semantic anchors we currently rely on. It never loads, launches or writes to
the target. Absolute cross-reference counts are raw 4-byte little-endian VA
occurrences; a zero count is evidence that no *direct* absolute reference is
file-backed, not evidence that no consumer exists (the consumer may live in a
protected section or compute the address).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import pefile

TARGETS = [
    "codoMP_client_shipRetail.exe",
    "codoMP_client_shipRetailBase.dll",
    "TCLS/ClientBase.dll",
    "TCLS/Client.exe",
]

ANCHORS = [
    b"TCLS_SHAREDMEMEMORY",
    b"TCLS_TASMEMORY_",
    b"\\Global\\TenP_TS_",
    b"WIN_NO_TCLS",
    b"WIN_ERROR",
    b"-src=tgp",
    b"+unattended",
    b"TAS-3AAC03A5-7D57-4c80-A175-0E4BEA43EE41-",
    b"PT-81634493-9d70-46be-8157-9e032cc0fd86-",
]

DATA_DIRECTORY_NAMES = {
    0: "export", 1: "import", 2: "resource", 3: "exception", 4: "certificate",
    5: "basereloc", 6: "debug", 7: "architecture", 8: "globalptr", 9: "tls",
    10: "loadconfig", 11: "boundimport", 12: "iat", 13: "delayimport", 14: "clr",
}


def section_rows(pe: pefile.PE) -> list[dict]:
    rows = []
    for section in pe.sections:
        name = section.Name.decode(errors="replace").strip("\x00")
        rows.append({
            "name": name,
            "virtual_address": section.VirtualAddress,
            "virtual_size": section.Misc_VirtualSize,
            "raw_pointer": section.PointerToRawData,
            "raw_size": section.SizeOfRawData,
            "characteristics": section.Characteristics,
        })
    return rows


def section_of_file_offset(rows: list[dict], offset: int) -> str | None:
    for row in rows:
        start = row["raw_pointer"]
        end = start + row["raw_size"]
        if start <= offset < end:
            return row["name"]
    return None


def section_of_rva(rows: list[dict], rva: int) -> str | None:
    for row in rows:
        if row["virtual_address"] <= rva < row["virtual_address"] + max(row["virtual_size"], row["raw_size"]):
            return row["name"]
    return None


def scan_target(root: Path, relative: str) -> dict:
    path = root.joinpath(*relative.split("/"))
    record: dict = {"path": relative, "exists": path.is_file()}
    if not path.is_file():
        return record
    data = path.read_bytes()
    record["bytes"] = len(data)
    record["sha256"] = hashlib.sha256(data).hexdigest()
    pe = pefile.PE(str(path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    rows = section_rows(pe)
    record.update({
        "machine": hex(pe.FILE_HEADER.Machine),
        "image_base": base,
        "entry_point_rva": pe.OPTIONAL_HEADER.AddressOfEntryPoint,
        "sections": rows,
        "data_directories": [
            {"index": index, "name": DATA_DIRECTORY_NAMES[index],
             "virtual_address": directory.VirtualAddress, "size": directory.Size}
            for index, directory in enumerate(pe.OPTIONAL_HEADER.DATA_DIRECTORY)
            if directory.VirtualAddress or directory.Size
        ],
    })
    anchors = []
    for pattern in ANCHORS:
        hit = data.find(pattern)
        if hit < 0:
            continue
        section = section_of_file_offset(rows, hit)
        rva = None
        for row in rows:
            if row["name"] == section:
                rva = row["virtual_address"] + (hit - row["raw_pointer"])
                break
        entry = {
            "pattern": pattern.decode("latin-1"),
            "file_offset": hit,
            "section": section,
            "rva": rva,
            "va": base + rva if rva is not None else None,
            "absolute_reference_count": 0,
            "absolute_reference_sites": [],
        }
        if rva is not None:
            needle = struct.pack("<I", base + rva)
            cursor = 0
            sites = []
            while True:
                found = data.find(needle, cursor)
                if found < 0:
                    break
                cursor = found + 1
                sites.append({"file_offset": found, "section": section_of_file_offset(rows, found)})
            entry["absolute_reference_sites"] = sites[:16]
            entry["absolute_reference_count"] = len(sites)
        anchors.append(entry)
    record["anchor_strings"] = anchors
    # UTF-16 variants matter for TCLS wide-char APIs.
    wide = []
    for pattern in ANCHORS[:3]:
        wide_pattern = pattern.decode("latin-1").encode("utf-16le")
        hit = data.find(wide_pattern)
        if hit >= 0:
            wide.append({"pattern": pattern.decode("latin-1"), "encoding": "utf-16le",
                         "file_offset": hit, "section": section_of_file_offset(rows, hit)})
    record["anchor_strings_utf16"] = wide
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = args.client_dir.resolve(strict=True)
    report = {
        "build": 1649370,
        "client_dir": str(root),
        "method": "read-only pefile + raw byte search; no process started",
        "limitations": [
            "Absolute reference counts only cover file-backed bytes.",
            "Protected sections (.tp3/.tvm0/.tls) may decrypt consumers at runtime.",
            "A zero count does not prove the string is unused.",
        ],
        "targets": [scan_target(root, relative) for relative in TARGETS],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
