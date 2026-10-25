"""Call a 32-bit client function from a remote thread and report the result.

The client's network layer has no usable inbound queue, so the only way to
feed it a server message is to invoke the engine's own consumer directly.
Everything here goes through 32-bit-safe APIs: the client is WOW64, so the
thread must be created with the 32-bit entry point and the payload page has to
live inside the client's low 4 GB address space.

    python tools/inject_call_1649370.py --pid 1234 --fn 0x472d80 --arg 0x12345678
    python tools/inject_call_1649370.py --pid 1234 --blob runs/gamestate-native.bin --fn 0x472d80
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.CreateRemoteThread.restype = W.HANDLE

PROCESS_ALL = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40
MEM_RELEASE = 0x8000


class Entry(ctypes.Structure):
    _fields_ = [("result", W.DWORD), ("fn", W.DWORD), ("arg", W.DWORD)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--fn", type=lambda v: int(v, 0), required=True,
                    help="client function VA to call")
    ap.add_argument("--arg", type=lambda v: int(v, 0), default=0,
                    help="dword argument (ignored when --blob is used)")
    ap.add_argument("--blob", help="file whose bytes are copied and passed by pointer")
    ap.add_argument("--ecx", type=lambda v: int(v, 0), default=None,
                    help="value to load into ecx before the call (thiscall)")
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    h = k32.OpenProcess(PROCESS_ALL, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    payload = b""
    if args.blob:
        with open(args.blob, "rb") as fh:
            payload = fh.read()

    # Layout: [Entry][payload][code]
    blob_size = len(payload)
    entry_size = ctypes.sizeof(Entry)
    code_offset = entry_size + blob_size + 0x10
    total = code_offset + 0x40

    remote = k32.VirtualAllocEx(h, None, total, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not remote:
        raise SystemExit(f"VirtualAllocEx failed: {ctypes.get_last_error()}")

    base = remote
    payload_va = base + entry_size
    code_va = base + code_offset

    # x86: mov dword [result], eax
    code = bytearray()
    code += b"\x60"                                  # pushad
    if payload:
        # push payload pointer; then push it as the single argument
        code += b"\x68" + struct.pack("<I", payload_va)   # push payload_va
    else:
        code += b"\x68" + struct.pack("<I", args.arg)     # push arg
    if args.ecx is not None:
        code += b"\xB9" + struct.pack("<I", args.ecx)    # mov ecx, value
    code += b"\xB8" + struct.pack("<I", args.fn)      # mov eax, fn
    code += b"\xFF\xD0"                               # call eax
    code += b"\xA3" + struct.pack("<I", base)         # mov [base], eax
    code += b"\x61"                                   # popad
    code += b"\xC3"                                   # ret

    entry = Entry(result=0, fn=args.fn, arg=args.arg)
    image = ctypes.create_string_buffer(bytes(entry) + payload + b"\x00" * (code_offset - entry_size - blob_size) + bytes(code), total)
    if not k32.WriteProcessMemory(h, ctypes.c_void_p(base), image, total, ctypes.byref(n)):
        raise SystemExit(f"WriteProcessMemory failed: {ctypes.get_last_error()}")

    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(code_va), None, 0, ctypes.byref(tid))
    if not th:
        raise SystemExit(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
    k32.WaitForSingleObject(th, int(args.timeout * 1000))
    k32.CloseHandle(th)

    buf = ctypes.create_string_buffer(ctypes.sizeof(Entry))
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, ctypes.sizeof(Entry), ctypes.byref(n))
    if ok:
        res, fn, arg = struct.unpack("<III", buf.raw)
        print(f"called {fn:#x}({arg:#x}) -> eax={res:#x}")
    else:
        print("ReadProcessMemory of result failed")

    k32.VirtualFreeEx(h, ctypes.c_void_p(base), 0, MEM_RELEASE)
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
