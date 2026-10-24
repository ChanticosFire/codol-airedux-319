"""Call one no-argument function on the client's main thread through ring_bridge.

    python tools/call_fn_1649370.py 0x813C20

Used to invoke CL_Init (0x813C20) which performs CL_Shutdown + CL_Init and then
sets net_state=7 - the gate that lets the client process inband packets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ring_bridge_1649370 import Client  # noqa: E402


def main() -> int:
    address = int(sys.argv[1], 0)
    client = Client()
    try:
        row = client.invoke_sequence([{"target": address, "args": []}], settle=1.0)
        print(json.dumps({k: row.get(k) for k in
                          ("status", "calls", "returned_eip", "process_alive_after")},
                         ensure_ascii=False, indent=2))
        print(json.dumps(client.status(), ensure_ascii=False, indent=2))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
