"""Send a 160-byte datagram to every UDP endpoint the client owns and watch the list state.

Round 194 established that the client binds six UDP ports but only 22011 ever sends the probes, and that replying to the
probe - which goes back to 22011 - never reaches the receive slot. This tests whether one of the other five ports is the
business receive: enumerate them live, send a 160-byte record to each, and poll [serverlist+0x1A0] for a change to 2.

    python tools/poke_ports.py --secs 60
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import socket
import struct
import subprocess
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_ALL = 0x1F0FFF
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CloseHandle.argtypes = [wt.HANDLE]

EXE = "codomp_client_shipretail.exe"
PAYLOAD = bytes(160)


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        if EXE.lower() in line.lower():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def udp_ports(pid: int) -> list[int]:
    cmd = ("Get-NetUDPEndpoint -OwningProcess %d -ErrorAction SilentlyContinue | "
           "Select-Object -ExpandProperty LocalPort" % pid)
    out = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd],
                         capture_output=True, text=True, errors="replace").stdout
    ports = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            ports.append(int(line))
    return sorted(set(ports))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secs", type=float, default=60.0)
    ap.add_argument("--wait", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=0.02)
    args = ap.parse_args()

    deadline = time.time() + args.wait
    h = None
    pid = 0
    while time.time() < deadline:
        pid = find_pid()
        if pid:
            h = k32.OpenProcess(PROCESS_ALL, False, pid)
            if h:
                probe = ctypes.create_string_buffer(4)
                got = ctypes.c_size_t()
                if k32.ReadProcessMemory(h, ctypes.c_void_p(0xE85C68), probe, 4,
                                         ctypes.byref(got)) and got.value == 4:
                    break
                k32.CloseHandle(h)
                h = None
        time.sleep(0.05)
    if not h:
        print("client never became readable")
        return 2

    def rd(va: int, n: int = 4) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else b""

    def u32(va: int) -> int | None:
        raw = rd(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

    try:
        # wait until the list object exists so the state code is meaningful
        for _ in range(1200):
            lobby = u32(0xE85C68)
            if lobby and u32(lobby + 0x1FC):
                break
            time.sleep(0.05)

        ports = udp_ports(pid)
        print(f"  client pid {pid}, udp ports: {ports}")

        sent_to = []
        for port in ports:
            for local in (0, 3074):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    if local:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        s.bind(("127.0.0.1", local))
                    s.sendto(PAYLOAD, ("127.0.0.1", port))
                    s.close()
                    sent_to.append(f"{port}(from {local})")
                except OSError as exc:
                    sent_to.append(f"{port}(from {local}) failed {type(exc).__name__}")
        print(f"  sent 160 bytes: {sent_to}")

        last = None
        t0 = time.time()
        codes: dict = {}
        while time.time() - t0 < args.secs:
            lobby = u32(0xE85C68)
            if lobby is None:
                print("  process gone")
                break
            if lobby:
                sl = u32(lobby + 0x1FC)
                o1 = u32(lobby + 0x1F8)
                code = u32(sl + 0x1A0) if sl else None
                status = u32(o1 + 0x120) if o1 else None
                f14 = u32(lobby + 0x1F4)
                codes[code] = codes.get(code, 0) + 1
                key = (code, status, f14)
                if key != last:
                    last = key
                    print(f"  t={time.time() - t0:6.2f}  1A0={code!s:>4}  "
                          f"status={status!s:>4}  1F4={f14!s:>2}  dw={u32(0x84ABA40)!s:>3}")
            time.sleep(args.interval)

        print(f"\n  list codes seen: {codes}")
        print(f"  saw code 2: {codes.get(2, 0)}")
        return 0
    finally:
        k32.CloseHandle(h)


if __name__ == "__main__":
    raise SystemExit(main())
