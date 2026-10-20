"""Show the applied state of every patch in a patch_runtime.py evidence file.

    python tools/show_patches.py runs/xxx/patch.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else
                r"E:\GAME\COD\codol-airedux\319\runs\20261023-m4-m3set\patch.json")
    if not path.is_file():
        print(f"missing: {path}")
        return 2
    doc = json.loads(path.read_text(encoding="utf-8"))
    print(f"{path.name}  build={doc.get('build')}  pid={doc.get('pid')}")
    for p in doc.get("patches", []):
        flag = "OK " if p.get("applied") and p.get("verified_after") else "!! "
        print(f"  {flag}{p.get('rva')}  {p.get('original')} -> {p.get('replacement')}"
              f"  applied={p.get('applied')} verified={p.get('verified_after')}")
        if p.get("reason"):
            print(f"        reason: {p['reason']}")
    for note in doc.get("notes", []):
        print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
