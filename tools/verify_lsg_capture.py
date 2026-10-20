"""Verify a local 1649370 LSG capture without exposing raw frames or keys.

Usage: python tools/verify_lsg_capture.py runs/<run-id> [--output runs/<run-id>/verification.json]
The run directory remains outside Git. Only booleans and frame sizes are emitted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server319.lsg_crypto import LsgProtocolError, derive_keys, parse_client_frame85
from server319.ticket import SESSION_KEY


def verify(run_dir: Path) -> dict:
    wanted = {
        "plaintext_frame": ("hello", "body_hex"),
        "gate_reply": ("gate", "reply_hex"),
        "plaintext_frame2": ("client_auth", "body_hex"),
        "token_reply": ("token", "reply_hex"),
        "plaintext_frame3": ("client_85", "body_hex"),
    }
    frames: dict[str, bytes] = {}
    memory_key = None
    for line in (run_dir / "lsg.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        spec = wanted.get(record.get("event"))
        if spec and record.get(spec[1]):
            frames[spec[0]] = bytes.fromhex(record[spec[1]])
        if record.get("event") == "key_object":
            match = re.search(r"^604 ptr=0x[0-9a-f]+ key=([0-9a-f]{32})\b",
                              record.get("reason", ""))
            if match:
                memory_key = bytes.fromhex(match.group(1))
    result = {
        "run_id": run_dir.name,
        "required_frames_present": False,
        "frame_lengths": {k: len(v) for k, v in frames.items()},
        "challenge_verified": False,
        "server_token_verified": False,
        "client_mac_verified": False,
        "client_plaintext_shape_verified": False,
        "memory_dec_key_matches": None,
    }
    required = ("hello", "gate", "client_auth", "token", "client_85")
    result["required_frames_present"] = all(k in frames for k in required)
    if not result["required_frames_present"]:
        return result
    try:
        keys = derive_keys(frames["hello"], frames["gate"],
                           frames["client_auth"], SESSION_KEY)
        result["challenge_verified"] = True
        token = frames["token"]
        result["server_token_verified"] = (
            len(token) in (14, 16) and int.from_bytes(token[:4], "little") == len(token) - 4
            and token[4:6] in (b"\x00\x83", b"\xab\x83")
            and token[6:14] == keys.challenge[8:]
            and not any(token[14:]))
        _, inner_type, payload = parse_client_frame85(frames["client_85"], keys)
        result["client_mac_verified"] = True
        result["client_plaintext_shape_verified"] = (
            inner_type == 0x86 and len(payload) >= 3 and payload[:3] == b"\x47\x03\x04")
        if memory_key is not None:
            result["memory_dec_key_matches"] = memory_key == keys.client_aes
    except (LsgProtocolError, ValueError, IndexError) as exc:
        result["failure"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.run_dir)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if all(result[k] for k in (
        "required_frames_present", "challenge_verified", "server_token_verified",
        "client_mac_verified", "client_plaintext_shape_verified")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
