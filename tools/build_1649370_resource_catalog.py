"""Export and verify the local Build 1649370 Cross Fire resource catalog."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOSE = (
    ("crossfire", "20261022-crossfire-loose-v461"),
    ("gametype", "20261022-gametype-loose-v461"),
    ("crash_tropical", "20261022-crash-tropical-loose-v461"),
    ("survival", "20261022-survival-loose-v461"),
    ("dmz", "20261022-dmz-loose-v461"),
)
FASTFILES = (
    ("crossfire", "20261021-1649370-crossfire-base", "ff_init_mp_cross_fire_V70.json"),
    ("gametype", "20261022-gametype-ff-v461", "ff_init_common_gametype_mp_V69.json"),
)
OUTPUT = ROOT / "evidence/experiments/20261022-codex-resource-catalog.json"
EXPECTED_EXE = "55f067ac24e7d5ea9bea5acd46a1514eb1b7780a627b73c2094f41133dce3ffd"


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    exe = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
    if sha_file(exe) != EXPECTED_EXE:
        raise ValueError("target Build 1649370 executable fingerprint mismatch")
    packs = []
    resources = []
    destinations = set()
    for label, folder in LOOSE:
        receipt_path = ROOT / "runs" / folder / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt["build"] != 1649370 or receipt["scope"] != "all_main"
                or receipt["decoded"] != receipt["listed"] or receipt["missing"]):
            raise ValueError(f"incomplete same-build loose pack: {folder}")
        source = Path(receipt["source"])
        if sha_file(source) != receipt["source_sha256"]:
            raise ValueError(f"source IFS fingerprint mismatch: {source}")
        count = Counter()
        decoded_bytes = 0
        for item in receipt["resources"]:
            member = Path(item["member"])
            if (not item["present"] or member.is_absolute() or ".." in member.parts
                    or len(member.parts) < 3 or member.parts[0].lower() != "main"):
                raise ValueError(f"unsafe or missing loose asset: {member}")
            local = ROOT / "runs" / folder / member
            if local.stat().st_size != item["decoded_size"] or sha_file(local) != item["decoded_sha256"]:
                raise ValueError(f"decoded asset fingerprint mismatch: {local}")
            stage = Path("devraw_shared").joinpath(*member.parts[1:]).as_posix()
            if stage.lower() in destinations:
                raise ValueError(f"duplicate private stage destination: {stage}")
            destinations.add(stage.lower())
            count[member.suffix.lower() or "(no extension)"] += 1
            decoded_bytes += item["decoded_size"]
            resources.append({"kind": "loose", "pack": label,
                              "member": member.as_posix(), "sha256": item["decoded_sha256"],
                              "size": item["decoded_size"],
                              "local": local.relative_to(ROOT).as_posix(), "stage": stage})
        packs.append({"kind": "loose", "label": label, "source": str(source),
                      "source_sha256": receipt["source_sha256"],
                      "receipt": receipt_path.relative_to(ROOT).as_posix(),
                      "receipt_sha256": sha_file(receipt_path),
                      "count": len(receipt["resources"]), "decoded_bytes": decoded_bytes,
                      "extensions": dict(sorted(count.items()))})
    for label, folder, receipt_name in FASTFILES:
        receipt_path = ROOT / "runs" / folder / receipt_name
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        source = Path(receipt["pack"])
        if sha_file(source) != receipt["pack_sha256"]:
            raise ValueError(f"signed IFS fingerprint mismatch: {source}")
        for item in receipt["members"]:
            if item["version"] != 461 or item["publisher_signature_verified"] is not True:
                raise ValueError(f"unverified or wrong-version fastfile: {item['name']}")
            local = ROOT / "runs" / folder / Path(item["name"]).name
            if local.stat().st_size != item["size"] or sha_file(local) != item["sha256"]:
                raise ValueError(f"fastfile fingerprint mismatch: {local}")
            stage = "client_shipretail/chinese/" + local.name
            if stage.lower() in destinations:
                raise ValueError(f"duplicate private stage destination: {stage}")
            destinations.add(stage.lower())
            resources.append({"kind": "signed_fastfile", "pack": label,
                              "member": item["name"], "sha256": item["sha256"],
                              "size": item["size"],
                              "local": local.relative_to(ROOT).as_posix(), "stage": stage,
                              "version": 461, "publisher_signature_verified": True,
                              "zone_asset_count": item["zone_asset_count"]})
        packs.append({"kind": "signed_fastfile", "label": label, "source": str(source),
                      "source_sha256": receipt["pack_sha256"],
                      "receipt": receipt_path.relative_to(ROOT).as_posix(),
                      "receipt_sha256": sha_file(receipt_path),
                      "count": len(receipt["members"]),
                      "decoded_bytes": sum(item["size"] for item in receipt["members"])})
    catalog = {"schema": 1, "build": 1649370,
               "target_exe_sha256": EXPECTED_EXE,
               "loose_count": sum(p["count"] for p in packs if p["kind"] == "loose"),
               "loose_bytes": sum(p["decoded_bytes"] for p in packs if p["kind"] == "loose"),
               "fastfile_count": sum(p["count"] for p in packs if p["kind"] == "signed_fastfile"),
               "fastfile_bytes": sum(p["decoded_bytes"] for p in packs if p["kind"] == "signed_fastfile"),
               "packs": packs, "resources": sorted(resources, key=lambda x: x["stage"].lower())}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: v for k, v in catalog.items() if k not in ("packs", "resources")},
                     ensure_ascii=True, indent=2))
    print("catalog_sha256", sha_file(OUTPUT))


if __name__ == "__main__":
    main()
