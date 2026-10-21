"""Verify development_mp.ff and inspect selected embedded config assets."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

COMMUNITY = Path(r"E:\GAME\COD\1649370")
CLIENT_EXE = Path(r"E:\GAME\COD\Original Client\codoMP_client_shipRetail.exe")
FASTFILE = COMMUNITY / "resources/v1649370/offline-resources/client_shipretail/chinese/development_mp.ff"
ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/20261021-1649370-zone"
REPORT = ROOT / "evidence/experiments/20261021-1649370-dev-configs.json"
SELECTED = {"bots.cfg", "devgui_maps_mp.cfg"}
sys.path.insert(0, str(COMMUNITY / "src"))

from codol_rebuild.resources.fastfile import decode_fastfile, validate_zone  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    zone_path = RUN / "development_mp.zone"
    verified = decode_fastfile(FASTFILE, CLIENT_EXE, zone_path)
    zone = zone_path.read_bytes()
    assets = []
    for entry in validate_zone(zone)["asset_entries"]:
        if entry["type"] != 36:
            continue
        blob = zone[entry["offset"]:entry["offset"] + entry["size"]]
        encoded_size, decoded_size = struct.unpack_from("<II", blob, 4)
        end = blob.find(b"\0", 16)
        if end < 0:
            raise ValueError("config asset name lacks NUL terminator")
        name = blob[16:end].decode("ascii")
        if name not in SELECTED:
            continue
        encoded = blob[end + 1:]
        if len(encoded) != encoded_size:
            raise ValueError(f"{name}: compressed size mismatch")
        data = zlib.decompress(encoded)
        if len(data) != decoded_size:
            raise ValueError(f"{name}: decoded size mismatch")
        destination = RUN / name
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f"{name}: existing decoded file differs")
        destination.write_bytes(data)
        lines = data.decode("ascii").splitlines()
        selected = [line.strip() for line in lines if line.strip().startswith(
            ("devgui_cmd", "set bot_", "set scr_game_spectatetype"))]
        assets.append({"name": name, "asset_index": entry["index"],
                       "size": len(data), "sha256": digest(data), "selected_lines": selected})
    if {asset["name"] for asset in assets} != SELECTED:
        raise ValueError("selected configs missing from verified zone")
    report = {"schema": 1, "fastfile": str(FASTFILE),
              "fastfile_sha256": digest(FASTFILE.read_bytes()),
              "publisher_signature_verified": verified["checks"]["publisher_signature_verified"],
              "zone_sha256": digest(zone), "zone_asset_count": verified["zone"]["asset_count"],
              "assets": assets,
              "limitation": "Config text proves shipped data only; command registration and runtime bot behavior remain unverified."}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "assets": [x["name"] for x in assets]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
