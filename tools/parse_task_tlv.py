"""Parse the TLVs inside a decrypted svc71 request payload.

Payloads start with 0x47 (bdService event) then a sub-tag, followed by a sequence
of typed values. This prints each field so the request's meaning is visible.

    python tools/parse_task_tlv.py runs/20261023-exp-h 1
    python tools/parse_task_tlv.py runs/20261023-exp-h        # all frames
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(r"E:\GAME\COD\codol-airedux\319")
sys.path.insert(0, str(ROOT))

from server319.lsg_crypto import LsgKeys, parse_client_frame85  # noqa: E402

TAGS = {0x03: "u8?", 0x06: "u16", 0x08: "u32", 0x0A: "u64",
        0x10: "str", 0x13: "u32b"}


def walk(payload: bytes) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(payload)
    while i < n:
        tag = payload[i]
        i += 1
        if tag == 0x47:
            # 47 03 <task id>: the middle byte is a fixed version marker, the
            # third byte is the svc71 task number.
            if i + 1 < n:
                ver = payload[i]
                task = payload[i + 1]
                out.append(f"EVENT 0x47 ver={ver:#04x} task={task}")
                i += 2
            continue
        if tag == 0x10:
            if i >= n:
                break
            length = payload[i]
            i += 1
            val = payload[i:i + length]
            i += length
            out.append(f"STR[{length}] {val[:90].decode('latin1')!r}")
            continue
        if tag in (0x08, 0x13):
            if i + 4 > n:
                break
            out.append(f"{TAGS[tag]} {struct.unpack_from('<I', payload, i)[0]}")
            i += 4
            continue
        if tag == 0x0A:
            if i + 8 > n:
                break
            out.append(f"u64 {struct.unpack_from('<Q', payload, i)[0]}")
            i += 8
            continue
        if tag == 0x06:
            if i + 2 > n:
                break
            out.append(f"u16 {struct.unpack_from('<H', payload, i)[0]}")
            i += 2
            continue
        if tag == 0x03:
            if i >= n:
                break
            out.append(f"u8 {payload[i]}")
            i += 1
            continue
        out.append(f"?? tag {tag:#04x} at {i - 1} (stop)")
        break
    return out


def main() -> int:
    run = Path(sys.argv[1] if len(sys.argv) > 1 else
               r"E:\GAME\COD\codol-airedux\319\runs\20261023-exp-h")
    want = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    keys = None
    sidecar = run / "lsg.jsonl.keys.jsonl"
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        if "keys" in obj:
            keys = LsgKeys(**{k: bytes.fromhex(v) for k, v in obj["keys"].items()})
            break
    if keys is None:
        print("no keys in sidecar")
        return 2

    frames = []
    for line in (run / "lsg.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("event") == "client_frame":
            frames.append(obj["body_hex"])

    for idx, body_hex in enumerate(frames, 1):
        if want and idx != want:
            continue
        counter, inner, payload = parse_client_frame85(bytes.fromhex(body_hex), keys)
        print(f"=== frame #{idx} counter={counter} inner={inner:#x} "
              f"payload={len(payload)}B ===")
        print(f" hex: {payload.hex()[:160]}")
        for line in walk(payload):
            print("  " + line)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
