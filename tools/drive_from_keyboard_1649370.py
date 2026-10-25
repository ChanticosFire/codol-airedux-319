"""Drive the snapshot's origin from the physical keyboard state.

Prediction is blocked in this build (see 1649370-STATUS.md 530-552), so the
client never moves itself.  The confirmed path is the other way round: the server
writes `origin` into the snapshot and the client follows (measured: changing
0x0F from 336 to 386 moved `cl+0x3C` and `predictedPlayerState.origin` to 386 and
shifted the rendered frame).

This tool closes the loop with the keyboard: it samples `GetAsyncKeyState` (works
without focus) and moves the snapshot origin while a movement key is held.  The
game server rereads the snapshot file every send, so the client sees a continuous
walk.

    python tools/drive_from_keyboard_1649370.py --snapshot runs/snap-drive.bin --seconds 600
"""
from __future__ import annotations

import argparse
import struct
import time
from pathlib import Path

import ctypes

SLOTS = ((0x0F, 0), (0x18, 1), (0x14, 2))  # measured: 0x0F=x, 0x18=y, 0x14=z
KEYS = {
    "forward": 0x57,   # W
    "back": 0x53,      # S
    "left": 0x41,      # A
    "right": 0x44,     # D
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=600.0)
    parser.add_argument("--speed", type=float, default=6.0, help="metres per second")
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    data = bytearray(args.snapshot.read_bytes())
    origin = [struct.unpack_from("<f", data, off)[0] for off, _ in SLOTS]
    period = 1.0 / max(1.0, args.hz)
    deadline = time.monotonic() + args.seconds
    last_report = 0.0
    moved = 0.0
    while time.monotonic() < deadline:
        down = {name: bool(u.GetAsyncKeyState(vk) & 0x8000) for name, vk in KEYS.items()}
        dx = (1.0 if down["right"] else 0.0) - (1.0 if down["left"] else 0.0)
        dz = (1.0 if down["forward"] else 0.0) - (1.0 if down["back"] else 0.0)
        if dx or dz:
            step = args.speed * period
            origin[0] += dx * step
            origin[1] += dz * step
            moved += step
            for (off, comp) in SLOTS:
                struct.pack_into("<f", data, off, origin[comp])
            args.snapshot.write_bytes(data)
            now = time.monotonic()
            if not args.quiet and now - last_report > 0.5:
                last_report = now
                print(f"origin=({origin[0]:.2f},{origin[1]:.2f},{origin[2]:.2f}) moved={moved:.1f}m", flush=True)
        time.sleep(period)
    print(f"done moved={moved:.1f}m final=({origin[0]:.2f},{origin[1]:.2f},{origin[2]:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
