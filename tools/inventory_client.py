"""Read-only CODOL client inventory and 7z metadata comparison.

The script reads the client and archive. It writes only the requested report
files, and never extracts or executes archive members.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zlib
from pathlib import Path


def digest_file(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    crc = 0
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            sha.update(block)
            crc = zlib.crc32(block, crc)
    return sha.hexdigest().upper(), f"{crc & 0xFFFFFFFF:08X}"


def archive_entries(seven_zip: Path, archive: Path) -> dict[str, dict]:
    result = subprocess.run(
        [str(seven_zip), "l", "-slt", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"7z listing failed: {result.returncode}: {result.stderr!r}")
    # The installed 7-Zip 19.00 writes archive names in the Windows OEM code page.
    listing = result.stdout.decode("gbk").replace("\r\n", "\n")
    if "----------" not in listing:
        raise ValueError("7z listing has no entry separator")
    body = listing.split("----------", 1)[1]
    rows: dict[str, dict] = {}
    for block in body.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if " = " in line:
                key, value = line.split(" = ", 1)
                fields[key.strip()] = value.strip()
        raw_path = fields.get("Path")
        if not raw_path or fields.get("Attributes", "").startswith("D"):
            continue
        parts = raw_path.replace("\\", "/").split("/")
        if len(parts) < 2:
            raise ValueError(f"archive entry lacks expected root directory: {raw_path}")
        relative = "/".join(parts[1:])
        if relative in rows:
            raise ValueError(f"duplicate archive path: {relative}")
        rows[relative] = {
            "size": int(fields["Size"]),
            # 7-Zip omits CRC text for empty regular files.
            "crc32": fields["CRC"].upper() or "00000000",
        }
    if not rows:
        raise ValueError("no archive files found")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--seven-zip", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    client = args.client.resolve(strict=True)
    archive = args.archive.resolve(strict=True)
    seven_zip = args.seven_zip.resolve(strict=True)
    output = args.out.resolve()
    if not client.is_dir() or not archive.is_file():
        parser.error("client must be a directory and archive must be a file")
    if output == client or client in output.parents:
        parser.error("output must be outside the original client")

    archived = archive_entries(seven_zip, archive)
    local: dict[str, dict] = {}
    for path in sorted(client.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(client).as_posix()
        sha, crc = digest_file(path)
        local[relative] = {"size": path.stat().st_size, "sha256": sha, "crc32": crc}

    only_local = sorted(local.keys() - archived.keys())
    only_archive = sorted(archived.keys() - local.keys())
    mismatches = [
        {"path": name, "local": local[name], "archive": archived[name]}
        for name in sorted(local.keys() & archived.keys())
        if local[name]["size"] != archived[name]["size"]
        or local[name]["crc32"] != archived[name]["crc32"]
    ]
    report = {
        "schema_version": 1,
        "client": str(client),
        "archive": str(archive),
        "archive_size": archive.stat().st_size,
        "local_count": len(local),
        "archive_count": len(archived),
        "local_total_bytes": sum(row["size"] for row in local.values()),
        "only_local": only_local,
        "only_archive": only_archive,
        "mismatches": mismatches,
        "files": local,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("local_count", "archive_count", "local_total_bytes", "only_local", "only_archive", "mismatches")}, ensure_ascii=False))
    return 0 if not (only_local or only_archive or mismatches) else 1


if __name__ == "__main__":
    raise SystemExit(main())
