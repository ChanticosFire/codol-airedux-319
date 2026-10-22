"""Extract 1649370 common/hi gfx loose images from the original IFS packs.

Stage-8 file tracing showed the client asking for `hires/images/*.iwi` and
`main/images/*.iwi` (spark/glow/smoke/spotlight effects) that the five loose
packs do not carry.  The members live in `lf_init_common_gfx_V63.ifs`
(main/images) and `lf_hi_init_common_gfx_V8.ifs` (hires/images).

    python tools/extract_1649370_common_gfx.py --pack common_gfx
    python tools/extract_1649370_common_gfx.py --pack hi_gfx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"E:\GAME\COD\Original Client\IIPS\IIPSDownload")
IFS_DLL = Path(r"E:\GAME\COD\Original Client\IIPS\IFS2.dll")
IFS_SHA = "5b0324e0b2ba3545a6c02626287d4fbc6a3116594744f4647333982d85508421"
LEGACY = ROOT.parent / "CODOL2697/fbe7c395"
EXTRACTOR = LEGACY / "extract_local_ifs.exe"
EXTRACTOR_SHA = "82aa733ab9fa97e1ad551d7d6b1e44772a65793d2e50cdb7adcce6e0749e338e"
CODEC = LEGACY / "decode_loose_resources.py"
CODEC_SHA = "43a03053bf0ab693c5a3c3697b7522a32ec28737de2719394cb92fef12f9da54"
PACKS = {
    "common_gfx": ("lf_init_common_gfx_V63.ifs", ("main/images/", "main/sound/music/ui/")),
    "hi_gfx": ("lf_hi_init_common_gfx_V8.ifs", ("hires/",)),
}


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", choices=PACKS, default="common_gfx")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    pack_name, prefixes = PACKS[args.pack]
    out = (args.out or ROOT / "runs" / f"20261022-1649370-{args.pack}").resolve()
    if not out.is_relative_to((ROOT / "runs").resolve()):
        parser.error("output must be within 319/runs")
    source = SOURCE_ROOT / pack_name
    for path, expected in ((source, None), (IFS_DLL, IFS_SHA),
                           (EXTRACTOR, EXTRACTOR_SHA), (CODEC, CODEC_SHA)):
        if expected is not None and sha_file(path) != expected:
            raise ValueError(f"input fingerprint mismatch: {path}")
    import sys
    sys.path.insert(0, str(LEGACY))
    from decode_loose_resources import decode  # noqa: PLC0415

    out.mkdir(parents=True, exist_ok=True)
    resources = []
    with tempfile.TemporaryDirectory(prefix=f"{args.pack}-", dir=out) as temp:
        tempdir = Path(temp)
        alias = tempdir / source.name
        extracted = tempdir / "extracted"
        shutil.copyfile(source, alias)
        result = subprocess.run([str(EXTRACTOR), str(IFS_DLL), str(alias), str(extracted)],
                                capture_output=True, text=True, timeout=300)
        if result.returncode not in (0, 10):
            raise RuntimeError(f"IFS extraction failed: {result.returncode} {result.stderr}")
        listings = list(extracted.glob("*.lst"))
        if len(listings) != 1:
            raise ValueError("expected one member list")
        names = [line.replace("\\", "/") for line in
                 listings[0].read_text(encoding="utf-8-sig").splitlines()]
        selected = [name for name in names
                    if any(name.lower().startswith(prefix) for prefix in prefixes)
                    and name.lower().endswith((".iwi", ".mp3"))]
        print(f"{pack_name}: members={len(names)} selected={len(selected)}")
        for member in sorted(selected):
            rel = Path(member)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"unsafe member path: {member}")
            encoded = extracted / rel
            if not encoded.is_file():
                resources.append({"member": member, "present": False})
                continue
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
                              "decoded_sha256": hashlib.sha256(data).hexdigest(),
                              "decoded_size": len(data)})
    report = {
        "schema": 1, "build": 1649370, "source": str(source), "source_sha256": sha_file(source),
        "pack": args.pack, "scope": [f"{p}*.iwi|*.mp3" for p in prefixes],
        "decoded": sum(bool(r.get("present")) for r in resources),
        "missing": [r["member"] for r in resources if not r.get("present")],
        "resources": resources,
    }
    (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "resources"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
