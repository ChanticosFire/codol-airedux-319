"""Extract signed v461 fastfiles from a read-only IFS pack into 319/runs.

The IFS member boundaries include container bytes after each fastfile. Signed
fastfile bodies consist of complete 0x2000-byte blocks after a 0x115-byte
header, so trim only those trailing bytes and verify the publisher signature
and hash chain before accepting any extracted member.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_EXE = Path(r"E:\GAME\COD\Original Client\codoMP_client_shipRetail.exe")
COMMUNITY = Path(r"E:\GAME\COD\1649370")
sys.path.insert(0, str(COMMUNITY / "src"))

from codol_rebuild.resources.fastfile import (  # noqa: E402
    FastfileError, decode_fastfile, inspect_fastfile,
)
from ifs_entries import find_payloads, parse_names  # noqa: E402

HEADER = 0x115
BLOCK = 0x2000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "runs/20261021-1649370-map")
    args = parser.parse_args()
    pack = args.pack.resolve()
    out = args.out.resolve()
    if out == pack.parent or out.is_relative_to(pack.parent):
        raise SystemExit("Output must be outside the source IFS directory")
    raw = pack.read_bytes()
    names = parse_names(raw)
    offsets = [item[0] for item in find_payloads(raw)]
    if not names or len(names) != len(offsets):
        raise ValueError(f"name/magic count mismatch: {len(names)} != {len(offsets)}")
    out.mkdir(parents=True, exist_ok=True)
    members = []
    for index, name in enumerate(names):
        if not name.lower().endswith(".ff") or Path(name).name != name.split("/")[-1]:
            raise ValueError(f"unexpected member name: {name!r}")
        start = offsets[index]
        next_start = offsets[index + 1] if index + 1 < len(offsets) else len(raw)
        span = next_start - start
        max_count = (span - HEADER) // BLOCK
        if max_count < 3:
            raise ValueError(f"{name}: too few signed blocks")
        candidate = out / (Path(name).name + ".candidate")
        if candidate.exists():
            raise ValueError(f"unexpected existing scratch file: {candidate}")
        verified = None
        count = 0
        for trial in range(max_count, max(2, max_count - 16), -1):
            trial_end = start + HEADER + trial * BLOCK
            candidate.write_bytes(raw[start:trial_end])
            try:
                verified = decode_fastfile(candidate, CLIENT_EXE)
                count = trial
                break
            except FastfileError as error:
                if error.stage not in {"table_hash", "data_hash", "hash_table", "zlib", "zlib_padding"}:
                    raise
            finally:
                candidate.unlink()
        if verified is None:
            raise ValueError(f"{name}: no signed candidate within 16 blocks of member boundary")
        end = start + HEADER + count * BLOCK
        ff = out / Path(name).name
        data = raw[start:end]
        if ff.exists() and ff.read_bytes() != data:
            raise ValueError(f"{ff}: existing output differs")
        ff.write_bytes(data)
        outer = inspect_fastfile(ff)
        zone = out / (ff.stem + ".zone")
        verified = decode_fastfile(ff, CLIENT_EXE, zone)
        members.append({"name": name, "start": start, "end": end,
                        "container_bytes_after": next_start - end,
                        "size": len(data), "sha256": sha(data),
                        "version": outer["version"],
                        "publisher_signature_verified": verified["checks"]["publisher_signature_verified"],
                        "zone_size": zone.stat().st_size, "zone_sha256": sha(zone.read_bytes()),
                        "zone_asset_count": verified["zone"]["asset_count"]})
    report = {"schema": 1, "pack": str(pack), "pack_size": len(raw),
              "pack_sha256": sha(raw), "members": members}
    report_path = out / (pack.stem + ".json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
