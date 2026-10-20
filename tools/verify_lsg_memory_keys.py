#!/usr/bin/env python
"""Compare derived LSG AES keys with retained Build 1649370 memory samples.

The legacy key_object ``key=`` diagnostic is not authoritative: its probe
overwrote the value with a candidate from connection+0x604. The separate
``tail=`` bytes came directly from each object at pointer+0x80. This verifier
compares only the 16 bytes at tail offset 0x1C (object+0x9C) and emits booleans,
never raw keys or client identity fields.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server319.lsg_crypto import derive_keys  # noqa: E402
from server319.ticket import SESSION_KEY  # noqa: E402


def verify(run_dir: Path) -> dict:
    path = run_dir / "lsg.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def frame(event: str, field: str) -> bytes:
        row = next(row for row in rows if row.get("event") == event)
        return bytes.fromhex(row[field])

    keys = derive_keys(frame("plaintext_frame", "body_hex"),
                       frame("gate_reply", "reply_hex"),
                       frame("plaintext_frame2", "body_hex"), SESSION_KEY)
    samples: dict[str, bytes] = {}
    for row in rows:
        if row.get("event") != "key_object":
            continue
        reason = row.get("reason", "")
        match = re.fullmatch(r"(604|608) ptr=0x[0-9a-f]+ key=[0-9a-f]+ "
                             r"head=[0-9a-f]+ tail=([0-9a-f]{128})", reason)
        if match:
            samples[match.group(1)] = bytes.fromhex(match.group(2))[0x1C:0x2C]
    if set(samples) != {"604", "608"}:
        raise ValueError("missing_distinct_604_608_memory_samples")
    return {
        "run": run_dir.name,
        "build": 1649370,
        "challenge_verified": True,
        "client_aes_matches_604_object_9c": samples["604"] == keys.client_aes,
        "server_aes_matches_608_object_9c": samples["608"] == keys.server_aes,
        "cross_direction_mismatch": (samples["604"] != keys.server_aes
                                     and samples["608"] != keys.client_aes),
        "legacy_key_text_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, nargs="+")
    args = parser.parse_args()
    result = []
    for run_dir in args.run_dir:
        try:
            result.append(verify(run_dir))
        except (OSError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
            result.append({"run": run_dir.name, "verified": False,
                           "error_type": type(exc).__name__})
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if all(row.get("client_aes_matches_604_object_9c")
                    and row.get("server_aes_matches_608_object_9c")
                    and row.get("cross_direction_mismatch") for row in result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
