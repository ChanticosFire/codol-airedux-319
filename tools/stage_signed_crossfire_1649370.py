"""Replace one existing 1649370 runtime's Cross Fire FFs from the signed IFS.

Only the three exact verified publisher files are allowed. No runtime copy,
zone dump, or persistent extraction directory is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMUNITY = Path(r"E:\GAME\COD\1649370")
RUNS = (COMMUNITY / "workspaces/offline-runs").resolve()
PACK = Path(r"E:\GAME\COD\Original Client\IIPS\IIPSDownload\ff_init_mp_cross_fire_V70.ifs")
CLIENT_EXE = Path(r"E:\GAME\COD\Original Client\codoMP_client_shipRetail.exe")
PACK_SHA = "3ba43cf2c0d1944a9941debb9878781c1d58f99d264cd0f357493088365b28c8"
EXPECTED = {
    "mp_cross_fire.ff": "45b964b1386479d7e86ee8bcff30ed72bbbfbcbeb76dc5cb4b2b8e22b4fb9c7e",
    "mp_cross_fire_load.ff": "dd9caec41616cf1edd6a0320fc3d4bb5887028292f45c9cad798e98c782e5be5",
    "mp_cross_fire_const.ff": "0ca264e7480c48ac61a6a4b1a8c8880654762cdbef62dc7eb631b105f56c8673",
}
OLD = {
    "mp_cross_fire.ff": "2c398b006e0ccf589f8d54eeeb01e434fcfe151caea24a36a36d7a0738cb1cf2",
    "mp_cross_fire_load.ff": "0b04da671c933b6dcf7b5b656b4af442a25689cdd626fb876b5897e85e7872e6",
    "mp_cross_fire_const.ff": "b5f23ee5bae7da9b78e825bd4f236d273c019bcc1d55749c0a8736ff888fe124",
}
sys.path.insert(0, str(COMMUNITY / "src"))
from codol_rebuild.resources.fastfile import decode_fastfile, inspect_fastfile  # noqa: E402
from ifs_entries import find_payloads, parse_names  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/codex-native-ff-staged.json")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if runtime.name != "runtime" or runtime.parent.parent != RUNS:
        raise SystemExit("runtime must be an existing direct child of offline-runs")
    stage = runtime / "client_shipretail/chinese"
    if runtime.is_symlink() or runtime.is_junction() or stage.is_symlink() or stage.is_junction():
        raise SystemExit("refusing a linked runtime or map directory")
    if not stage.is_dir():
        raise SystemExit("existing runtime map directory is missing")
    before = {}
    for name in EXPECTED:
        target = stage / name
        if not target.is_file() or target.is_symlink():
            raise SystemExit(f"missing or linked map file: {target}")
        before[name] = sha(target.read_bytes())
        if before[name] not in (OLD[name], EXPECTED[name]):
            raise SystemExit(f"unrecognized existing map file: {target}")
    raw = PACK.read_bytes()
    if sha(raw) != PACK_SHA:
        raise SystemExit("IFS pack fingerprint differs from the verified 1649370 source")
    names = parse_names(raw)
    offsets = [item[0] for item in find_payloads(raw)]
    if len(names) != len(offsets) or set(Path(name).name for name in names) != set(EXPECTED):
        raise SystemExit(f"unexpected IFS member list: {names}")
    rows = []
    for position, name in enumerate(names):
        basename = Path(name).name
        start = offsets[position]
        next_start = offsets[position + 1] if position + 1 < len(offsets) else len(raw)
        count = (next_start - start - 0x115) // 0x2000
        verified = None
        for trial in range(count, max(2, count - 16), -1):
            data = raw[start:start + 0x115 + trial * 0x2000]
            if sha(data) == EXPECTED[basename]:
                verified = data
                break
        if verified is None:
            raise SystemExit(f"signed member boundary not found: {basename}")
        target = stage / basename
        if before[basename] == EXPECTED[basename]:
            rows.append({"name": basename, "before": before[basename], "after": before[basename],
                         "action": "already_current"})
            continue
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix=basename + ".", suffix=".candidate",
                                             dir=stage, delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(verified)
            inspection = inspect_fastfile(temp_path)
            decoded = decode_fastfile(temp_path, CLIENT_EXE)
            if inspection["version"] != 461 or not decoded["checks"]["publisher_signature_verified"]:
                raise ValueError(f"version or publisher signature invalid: {basename}")
            os.replace(temp_path, target)
            temp_path = None
            rows.append({"name": basename, "before": before[basename], "after": EXPECTED[basename],
                         "action": "replaced", "version": 461, "publisher_signature_verified": True,
                         "size": len(verified)})
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    report = {"schema": 1, "build": 1649370, "runtime": str(runtime), "pack": str(PACK),
              "pack_sha256": PACK_SHA, "files": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
