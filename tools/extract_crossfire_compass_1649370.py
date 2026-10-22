"""Extract Build 1649370's Cross Fire loose IWI set to a private run directory.

The 2.6.9.7 extractor is used only as an IFS container reader. The input IFS
is the SHA-bound 1649370 original package, and the decoded IWi09 result is
kept under 319/runs. Neither source archives nor shared libraries are edited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"E:\GAME\COD\Original Client\IIPS\IIPSDownload")
PACKS = {
    "crossfire": ("lf_init_mp_cross_fire_V10.ifs",
                  "c340793c2ea18e6e37cde3b94b9475aa6b7f91bd89c2c111eb54b8b119634386",
                  Path("main/images/compass_map_mp_cross_fire.iwi")),
    "gametype": ("lf_init_common_gametype_mp_V25.ifs",
                 "3f27b8b4f6fb9392d7340b8f491c10dc46616b35df4e2f63756bb4e10dae768d",
                 Path("main/images/dpad_ks_uav.iwi")),
    "crash_tropical": ("lf_init_mp_crash_tropical_V21.ifs",
                       "5605bd43ed2dd5ef5000e4f4ca1de977a350df16ce1a55d23eabf5d1304a2d6d",
                       Path("main/images/sun_flare_icbm.iwi")),
}
IFS_DLL = Path(r"E:\GAME\COD\Original Client\IIPS\IFS2.dll")
IFS_SHA = "5b0324e0b2ba3545a6c02626287d4fbc6a3116594744f4647333982d85508421"
LEGACY = ROOT.parent / "CODOL2697/fbe7c395"
EXTRACTOR = LEGACY / "extract_local_ifs.exe"
EXTRACTOR_SHA = "82aa733ab9fa97e1ad551d7d6b1e44772a65793d2e50cdb7adcce6e0749e338e"
CODEC = LEGACY / "decode_loose_resources.py"
CODEC_SHA = "43a03053bf0ab693c5a3c3697b7522a32ec28737de2719394cb92fef12f9da54"


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", choices=PACKS, default="crossfire")
    parser.add_argument("--out", type=Path, default=ROOT / "runs/20261022-crossfire-compass-v461")
    parser.add_argument("--all-main", action="store_true",
                        help="decode every carried main/ loose asset instead of only the compass")
    args = parser.parse_args()
    pack_name, source_sha, required_resource = PACKS[args.pack]
    source = SOURCE_ROOT / pack_name
    out = args.out.resolve()
    if not out.is_relative_to((ROOT / "runs").resolve()):
        parser.error("output must be within 319/runs")
    for path, expected in ((source, source_sha), (IFS_DLL, IFS_SHA),
                           (EXTRACTOR, EXTRACTOR_SHA), (CODEC, CODEC_SHA)):
        if sha_file(path) != expected:
            raise ValueError(f"input fingerprint mismatch: {path}")
    sys.path.insert(0, str(LEGACY))
    from decode_loose_resources import decode  # noqa: PLC0415

    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="crossfire-ifs-", dir=out) as temp:
        tempdir = Path(temp)
        alias = tempdir / source.name
        extracted = tempdir / "extracted"
        shutil.copyfile(source, alias)
        if sha_file(alias) != source_sha:
            raise ValueError("private archive copy changed")
        result = subprocess.run([str(EXTRACTOR), str(IFS_DLL), str(alias), str(extracted)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode not in (0, 10):
            raise RuntimeError(f"IFS extraction failed: {result.returncode} {result.stderr}")
        listings = list(extracted.glob("*.lst"))
        if len(listings) != 1:
            raise ValueError("expected one public IFS member list")
        names = {line.replace("\\", "/").lower(): line.replace("\\", "/")
                 for line in listings[0].read_text(encoding="utf-8-sig").splitlines()}
        original_name = names.get(required_resource.as_posix().lower())
        if original_name is None:
            raise ValueError(f"required IWI absent from IFS member list: {required_resource}")
        selected = ([name for key, name in names.items() if key.startswith("main/")]
                    if args.all_main else [original_name])
        resources = []
        for member in sorted(selected):
            rel = Path(member)
            if rel.is_absolute() or ".." in rel.parts or rel.parts[0].lower() != "main":
                raise ValueError(f"unsafe member path: {member}")
            encoded = extracted / rel
            if not encoded.is_file():
                # The extractor reports directory-only and skipped members as
                # missing. Record them separately instead of inventing bytes.
                resources.append({"member": member, "present": False})
                continue
            encoded_sha = sha_file(encoded)
            raw = encoded.read_bytes()
            data = raw if raw.startswith(b"IWff") else decode(raw, rel.name)
            if rel.suffix.lower() == ".iwi" and (len(data) < 32 or data[:4] != b"IWi\x09"):
                raise ValueError(f"decoded IWI header invalid: {member}")
            destination = out / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != data:
                raise ValueError(f"existing decoded resource differs: {destination}")
            destination.write_bytes(data)
            resources.append({"member": member, "present": True,
                              "encoded_sha256": encoded_sha,
                              "decoded_sha256": hashlib.sha256(data).hexdigest(),
                              "decoded_size": len(data)})
        if not any(r.get("present") and r["member"].lower() == required_resource.as_posix().lower()
                   for r in resources):
            raise ValueError(f"required IWI not carried or decoded: {required_resource}")
        report = {
            "schema": 1, "build": 1649370, "source": str(source),
            "source_sha256": source_sha, "ifs_dll_sha256": IFS_SHA,
            "extractor_sha256": EXTRACTOR_SHA, "codec_sha256": sha_file(CODEC),
            "extractor_exit_code": result.returncode,
            "scope": "all_main" if args.all_main else "required_resource_only",
            "listed": len(resources), "decoded": sum(bool(r.get("present")) for r in resources),
            "missing": [r["member"] for r in resources if not r.get("present")],
            "resources": resources,
        }
    (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "resources"}, indent=2))


if __name__ == "__main__":
    main()
