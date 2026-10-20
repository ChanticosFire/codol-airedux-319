"""Decrypt captured client frames using the sidecar session keys.

lsg_derived.py writes <log>.keys.jsonl when LSG_DUMP_KEYS=1. Replay each captured
body_hex through the same parser the server uses, so the TLVs the client sent
become readable.

    python tools/decrypt_frames.py runs/20261023-exp-h
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\GAME\COD\codol-airedux\319")
sys.path.insert(0, str(ROOT))

from server319.lsg_crypto import LsgKeys, parse_client_frame85  # noqa: E402


def load_keys(path: Path) -> LsgKeys | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        raw = obj.get("keys")
        if isinstance(raw, dict):
            return LsgKeys(**{k: bytes.fromhex(v) for k, v in raw.items()})
    return None


def main() -> int:
    run = Path(sys.argv[1] if len(sys.argv) > 1 else
               r"E:\GAME\COD\codol-airedux\319\runs\20261023-exp-h")
    log = run / "lsg.jsonl"
    keys_file = run / "lsg.jsonl.keys.jsonl"
    if not log.is_file():
        print(f"missing {log}")
        return 2
    if not keys_file.is_file():
        print(f"missing {keys_file} (run with LSG_DUMP_KEYS=1)")
        return 3
    keys = load_keys(keys_file)
    if keys is None:
        print("no usable key record")
        return 4
    print(f"keys loaded: client_aes={keys.client_aes.hex()[:16]}…")

    # task id per counter, to label each decrypted frame
    labels: dict[int, str] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("event") == "task_request":
            reason = obj.get("reason") or ""
            parts = dict(p.split("=") for p in reason.split() if "=" in p)
            counter = obj.get("frames_seen")
            if "task" in parts and counter is not None:
                labels.setdefault(int(counter), parts["task"])

    shown = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("event") != "client_frame":
            continue
        body = bytes.fromhex(obj.get("body_hex") or "")
        if not body:
            continue
        shown += 1
        print(f"\n--- client_frame #{shown} ({len(body)} bytes) ---")
        try:
            counter, inner, payload = parse_client_frame85(body, keys)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  parse failed: {type(exc).__name__}: {exc}")
            continue
        print(f"  counter={counter} inner={inner:#x} payload_len={len(payload)}")
        print(f"  payload: {payload[:120].hex()}")
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in payload[:120])
        print(f"  ascii  : {text}")
        if shown >= 8:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
