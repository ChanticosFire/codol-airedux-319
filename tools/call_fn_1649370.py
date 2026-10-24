"""Call one function on the client's main thread through ring_bridge.

    python tools/call_fn_1649370.py 0x5C83D0 --arg 1
    python tools/call_fn_1649370.py 0x813C20

`--arg` values are pushed in order (cdecl/stdcall).  `--eax` / `--ecx` set the
corresponding registers first, which matters for thunks that take the "this" or a
mode value in a register (e.g. CL_Init reads its mode from eax in some paths).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ring_bridge_1649370 import Client  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("address", type=lambda v: int(v, 0))
    ap.add_argument("--arg", type=lambda v: int(v, 0), action="append", default=[])
    ap.add_argument("--eax", type=lambda v: int(v, 0))
    ap.add_argument("--ecx", type=lambda v: int(v, 0))
    ap.add_argument("--settle", type=float, default=1.0)
    args = ap.parse_args()
    call: dict = {"target": args.address, "args": args.arg}
    if args.eax is not None:
        call["eax"] = args.eax
    if args.ecx is not None:
        call["ecx"] = args.ecx
    client = Client()
    try:
        row = client.invoke_sequence([call], settle=args.settle)
        print(json.dumps({k: row.get(k) for k in
                          ("status", "calls", "returned_eip", "process_alive_after")},
                         ensure_ascii=False, indent=2))
        status = client.status()
        print(json.dumps({k: status.get(k) for k in ("stage", "state", "connection")},
                         ensure_ascii=False, indent=2))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
