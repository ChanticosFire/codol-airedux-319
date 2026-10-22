"""Check whether the per-process WFP policy permits raw loopback TCP."""
from __future__ import annotations

import ctypes as C
import json
import socket
import struct
import threading
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    result = {"schema": 1, "date": datetime.now(timezone.utc).isoformat(),
              "purpose": "raw TCP from client process to 127.0.0.1:28969"}
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 28969))
    listener.listen(1)
    listener.settimeout(8)
    accepted = {}

    def receive() -> None:
        try:
            peer, address = listener.accept()
            accepted["peer"] = list(address)
            peer.close()
        except OSError as error:
            accepted["error"] = repr(error)

    worker = threading.Thread(target=receive, daemon=True)
    worker.start()
    handle = None
    try:
        result["pid"] = pid = sc.find_pid()
        handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
        sockaddr = int(sc.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x04))
        log = sockaddr + 0x100
        sc.w(handle, sockaddr, bytes.fromhex("020071297f0000010000000000000000"))
        cave = int(sc.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
        code = bytearray(b"\x6a\x06\x6a\x01\x6a\x02\xff\x15\x48\x85\xca\x00")
        code += b"\xa3" + struct.pack("<I", log)
        code += b"\x6a\x10\x68" + struct.pack("<I", sockaddr) + b"\x50"
        code += b"\xff\x15\xf0\x84\xca\x00"
        code += b"\xa3" + struct.pack("<I", log + 4)
        code += b"\xff\x15\x3c\x85\xca\x00"
        code += b"\xa3" + struct.pack("<I", log + 8) + b"\x31\xc0\xc3"
        sc.w(handle, cave, bytes(code))
        tid = W.DWORD()
        thread = sc.k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
        result["thread_wait"] = sc.k32.WaitForSingleObject(thread, 5000)
        result["socket"] = hex(sc.u32(handle, log))
        result["connect_return"] = C.c_int32(sc.u32(handle, log + 4)).value
        result["wsa_error"] = sc.u32(handle, log + 8)
        worker.join(timeout=8)
        result["accepted"] = accepted
    finally:
        listener.close()
        if handle:
            sc.k32.CloseHandle(handle)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = ROOT / "evidence" / "experiments" / f"{stamp}-1649370-raw-tcp.json"
        target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"evidence": str(target), **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
