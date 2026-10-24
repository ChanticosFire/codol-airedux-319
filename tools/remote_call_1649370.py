"""Call a function inside CODOL from a fresh remote thread.

Hijacking the WinMain thread works only while that thread is running user code.
Once the client settles into a message-wait the suspended context is resumed
straight back into `WaitForSingleObject` and the injected cave never executes -
`main_call_1649370.py` silently reports eax=0 in that state.

`CreateRemoteThread` sidesteps the problem entirely: the stub runs on its own
thread, records the return value and exits.  It is safe for pure/query functions
(no thread-affine state); mutating game state from a foreign thread is riskier.

    python tools/remote_call_1649370.py --target 0x7F4F10 --arg 0x9d
    python tools/remote_call_1649370.py --target 0x803830
    python tools/remote_call_1649370.py --target 0x5BE730 --ecx connection
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
import time
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)

k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
k32.CreateRemoteThread.restype = W.HANDLE
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
k32.WaitForSingleObject.restype = W.DWORD
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]

CONN_ENCODED = 0x331C0C8
CONN_XOR = 0xD362501F


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--ecx", default=None, help="'connection' or hex")
    ap.add_argument("--arg", type=lambda v: int(v, 0), action="append", default=[],
                    help="stack argument pushed in call order (cdecl)")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    pid = args.pid or find_pid()
    handle = k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")

    def read(va: int, n: int) -> bytes | None:
        buf = C.create_string_buffer(n)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, n, C.byref(got)) or got.value != n:
            return None
        return buf.raw

    def u32(va: int) -> int | None:
        d = read(va, 4)
        return struct.unpack("<I", d)[0] if d else None

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    encoded = u32(CONN_ENCODED) or 0
    connection = encoded ^ CONN_XOR
    ecx = None
    if args.ecx:
        ecx = connection if args.ecx == "connection" else int(args.ecx, 0)

    block = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not block:
        raise SystemExit("VirtualAllocEx failed")
    result_slot = block + 0x400

    code = bytearray()
    code += b"\x60"                                       # pushad
    if ecx is not None:
        code += b"\xB9" + struct.pack("<I", ecx)           # mov ecx,imm
    for value in reversed(args.arg):
        code += b"\x68" + struct.pack("<I", value)         # push value
    rel = (args.target - (block + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE8" + struct.pack("<I", rel)               # call target
    if args.arg:
        code += b"\x83\xC4" + struct.pack("<B", 4 * len(args.arg))   # add esp,N
    code += b"\xA3" + struct.pack("<I", result_slot)       # mov [slot],eax
    code += b"\x61"                                        # popad
    code += b"\x33\xC0\xC2\x04\x00"                        # xor eax,eax; ret 4

    if not write(block, bytes(code)):
        raise SystemExit("write code failed")
    k32.FlushInstructionCache(handle, C.c_void_p(block), len(code))

    tid = W.DWORD()
    thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(block), None, 0, C.byref(tid))
    report: dict = {
        "pid": pid, "target": hex(args.target), "block": hex(block),
        "connection": hex(connection), "connection_valid": 0x10000 <= connection < 0x7FFF0000,
        "ecx": hex(ecx) if ecx is not None else None,
        "args": [hex(a) for a in args.arg],
    }
    if not thread:
        report.update(status="CreateRemoteThread failed", error=C.get_last_error())
        print(json.dumps(report, indent=2))
        return 1

    wait = k32.WaitForSingleObject(thread, int(args.timeout * 1000))
    report["wait"] = "signaled" if wait == 0 else ("timeout" if wait == 0x102 else str(wait))
    time.sleep(0.2)
    report["result_eax"] = hex(u32(result_slot) or 0)
    report["code"] = bytes(code).hex()
    k32.CloseHandle(thread)
    k32.CloseHandle(handle)
    print(json.dumps(report, indent=2))
    return 0 if wait == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
