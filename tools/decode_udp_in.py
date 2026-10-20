"""Decode the UDP datagrams the client sends to the lobby port.

lobby_udp records every received datagram in a `udp_in` event with a `hex` field. This
walks those events, groups identical payloads, and prints a hex/ASCII view of each so the
protocol can be inferred without guessing.

    python tools/decode_udp_in.py runs/20261024-noecho/lobby_udp.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def hexdump(data: bytes, width: int = 16) -> list[str]:
    out = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"    {off:04x}  {hexpart:<{width * 3}}  {text}")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"not found: {path}")
        return 3

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    counts = Counter(e.get("event") for e in events)
    print(f"{path.name}: {len(events)} events")
    print(f"  counts: {dict(counts)}")

    udp = [e for e in events if e.get("event") == "udp_in"]
    print(f"\nudp_in events: {len(udp)}")
    if not udp:
        return 0

    by_len: dict[int, list[str]] = {}
    for e in udp:
        h = e.get("hex") or ""
        by_len.setdefault(len(h) // 2, []).append(h)

    print(f"distinct lengths: {sorted(by_len)}")
    for length in sorted(by_len):
        payloads = Counter(by_len[length])
        print(f"\n--- length {length}, {len(by_len[length])} datagrams, "
              f"{len(payloads)} distinct payload(s) ---")
        for h, n in payloads.most_common(3):
            data = bytes.fromhex(h)
            print(f"  x{n}:")
            for line in hexdump(data):
                print(line)

    # where did they come from
    srcs = Counter(e.get("src") for e in udp)
    print(f"\nsources: {dict(srcs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
