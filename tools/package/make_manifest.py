"""Build MANIFEST.json for the packaged CODOL 1649370 runtime.

Records path / size / sha256 for every file in the package, plus the identity of
the verified runtime executable and an explicit list of the large directories
(main/, hires/) that are deliberately omitted and must be synced from an
existing runtime.
"""
import hashlib
import json
import pathlib
import sys

PKG = pathlib.Path(sys.argv[1])
EXPECTED_EXE = "141215dd38754d39a45e9b112345049293579006ea98573a0ba51cc4d55ad380"
OMITTED = ["runtime/main", "runtime/hires"]

TREE_NAMES = {"server1649370", "server319", "codol_rebuild", "tools", "patches", "data", "runtime"}


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    files = []
    total = 0
    for p in sorted(PKG.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(PKG).as_posix()
        size = p.stat().st_size
        total += size
        entry = {"path": rel, "size": size, "sha256": sha256(p)}
        files.append(entry)

    exe = PKG / "runtime" / "codol1649370-offline.exe"
    exe_sha = sha256(exe) if exe.is_file() else None
    manifest = {
        "package": "CODOL-1649370-runtime-package",
        "build": "1649370",
        "client_version": "3.19.26.22",
        "protocol_shortversion": "1.1.1.13",
        "created": "2026-10-25",
        "file_count": len(files),
        "total_bytes": total,
        "runtime_exe": {
            "path": "runtime/codol1649370-offline.exe",
            "sha256": exe_sha,
            "expected_sha256": EXPECTED_EXE,
            "match": exe_sha == EXPECTED_EXE,
        },
        "omitted_directories": [
            {
                "path": name,
                "bytes": 7414223000 if name.endswith("main") else 7160500000,
                "reason": "original game resources; sync from an existing runtime "
                          "or the original client install",
            }
            for name in OMITTED
        ],
        "files": files,
    }
    out = PKG / "MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print("  files       : %d" % len(files))
    print("  total       : %.1f MB" % (total / 1048576))
    print("  runtime exe : %s  match=%s" % (exe_sha, exe_sha == EXPECTED_EXE))
    print("  manifest    : %s (%.1f KB)" % (out, out.stat().st_size / 1024))
    return 0 if exe_sha == EXPECTED_EXE else 1


if __name__ == "__main__":
    sys.exit(main())
