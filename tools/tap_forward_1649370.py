"""Forward the client's outbound packets captured by the 0x674F30 drain hook.

Section 833 established a zero-interference tap: hooking the drain with
`--capture 1024 --capture-src arg0` makes the cave copy the destination buffer
into `slot+0x40` on every call, at the exact moment the packet is moved out of
ring_a.  The payload starts at offset 0x30 of that buffer (the first 0x30 bytes
are drain bookkeeping).

This tool polls the capture area, detects new packets by their `ffffffff` OOB
prefix or their type word, and sends each one to the game server over UDP.

    python tools/tap_forward_1649370.py --slot 0xE9C0000 --target 127.0.0.1:28969 --seconds 60
"""
from __future__ import annotations

import argparse
import ctypes
import socket
import struct
import sys
import time
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

CAPTURE_OFF = 0x40
PAYLOAD_OFF = 0x30


def find_pid() -> int:
    import subprocess
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'codol1649370-offline.exe' }"
         " | Select-Object -First 1).ProcessId"]).decode().strip()
    return int(out) if out else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int)
    ap.add_argument("--slot", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--target", required=True, help="host:port of the game server")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--capture", type=int, default=1024)
    args = ap.parse_args()

    pid = args.pid or find_pid()
    if not pid:
        raise SystemExit("client not found")
    h = k32.OpenProcess(0x438, False, pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    def rd(va: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, size, ctypes.byref(n))
        return buf.raw if ok and n.value == size else None

    host, port_s = args.target.rsplit(":", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (host, int(port_s))

    cap_va = args.slot + CAPTURE_OFF
    seen = set()
    sent = 0
    t0 = time.monotonic()
    print(f"tap pid={pid} slot={args.slot:#x} -> {dest}", flush=True)
    while time.monotonic() - t0 < args.seconds:
        blob = rd(cap_va, args.capture)
        if blob:
            # Locate the packet: prefer the OOB prefix, else start at PAYLOAD_OFF.
            idx = blob.find(b"\xff\xff\xff\xff")
            start = idx if idx >= 0 else PAYLOAD_OFF
            tail = blob[start:]
            end = tail.find(b"\x00")
            if end < 0:
                end = len(tail)
            payload = tail[:end].rstrip(b"\x00")
            if len(payload) >= 8 and payload not in seen:
                seen.add(payload)
                try:
                    sock.sendto(payload, dest)
                    sent += 1
                    text = payload[:60]
                    print(f"[tap] len={len(payload)} -> {dest} head={text!r}", flush=True)
                except OSError as exc:
                    print(f"[tap] send failed: {exc}", flush=True)
        time.sleep(0.02)
    print(f"[tap] done sent={sent} unique={len(seen)}", flush=True)
    sock.close()
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
