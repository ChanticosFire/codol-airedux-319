"""Drive the loopback ring and sample parser hooks inside one process.

The client crashes ~163ms after reaching state 7, so a separate process cannot
read the hook counters in time.  This script does the forwarding itself and
reads the counters the instant the state flips.

    python tools/fast_forward_1649370.py --pid 1234 --port 29150 --seconds 6
"""
from __future__ import annotations

import argparse
import ctypes
import socket
import struct
import sys
import time
from ctypes import wintypes as W

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

import ring_bridge_1649370 as rb  # noqa: E402

STATE = rb.STATE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--target", default="127.0.0.1:28969")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--hook", type=lambda v: int(v, 0), action="append", default=[],
                    help="hook slot base (count is the first dword)")
    args = ap.parse_args()

    host, port_text = args.target.rsplit(":", 1)
    target = (host, int(port_text))

    client = rb.Client()  # finds the pid itself
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", args.port))
    sock.setblocking(False)

    deadline = time.monotonic() + args.seconds
    sent = received = injected = 0
    last_state = None
    seen7 = None
    samples = []

    while time.monotonic() < deadline:
        state = client.u32(STATE)
        if not client.read(STATE, 4):
            print(f"[t={time.monotonic():.3f}] client gone", flush=True)
            break
        if state != last_state:
            print(f"[t={time.monotonic():.3f}] state {last_state} -> {state}", flush=True)
            last_state = state
        if state == 7 and seen7 is None:
            seen7 = time.monotonic()
            for slot in args.hook:
                samples.append((round(time.monotonic(), 4), hex(slot), client.u32(slot)))
            print(f"[t={seen7:.3f}] STATE=7 samples={samples}", flush=True)

        # forward client -> gs
        for packet in client.drain_ring_a():
            sock.sendto(packet["payload"], target)
            sent += 1

        # gs -> client
        for _ in range(64):
            try:
                data, _src = sock.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError:
                break
            received += 1
            result = client.inject_oob_raw(data, 2, 0, b"\0\0\0\0")
            if result.get("status") == "queued":
                injected += 1

        time.sleep(0.0005)

    state = client.u32(STATE)
    print(f"sent={sent} received={received} injected={injected} "
          f"final_state={state} seen7={seen7}", flush=True)
    if seen7 is not None and args.hook:
        for slot in args.hook:
            print(f"hook {slot:#x} = {client.u32(slot)}", flush=True)
    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
