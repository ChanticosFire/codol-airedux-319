"""Call a 32-bit client function from a remote thread and report the result.

The client has no working inbound network queue, so the only way to feed it a
server message is to invoke the engine's own consumer directly. Everything goes
through 32-bit-safe APIs: the client is WOW64, so the payload page has to live
inside the client's low 4 GB address space.

Layout of the remote page:  [Entry][payload][msg_t][code]

    Entry { dword result; dword fn; dword arg; }

With --msg a `msg_t` is built in the page (data/cursize/maxsize/readcount/oob)
and its address is passed in ecx, which is what __thiscall consumers such as
CL_ParseGamestate (0x472D80) expect.

    python tools/inject_call_1649370.py --pid 1234 --fn 0x5c8a70
    python tools/inject_call_1649370.py --pid 1234 --fn 0x472d80 --msg --blob runs/gamestate-native.bin
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

MSG_T_SIZE = 0x30


class Entry(ctypes.Structure):
    _fields_ = [("result", W.DWORD), ("fn", W.DWORD), ("arg", W.DWORD)]


def build_code(fn: int, ecx: int | None, push_value: int, result_va: int) -> bytes:
    code = bytearray()
    code += b"\x60"                                    # pushad
    if ecx is not None:
        code += b"\xB9" + struct.pack("<I", ecx)       # mov ecx, value
    code += b"\x68" + struct.pack("<I", push_value)    # push arg
    code += b"\xB8" + struct.pack("<I", fn)            # mov eax, fn
    code += b"\xFF\xD0"                                # call eax
    code += b"\xA3" + struct.pack("<I", result_va)     # mov [result], eax
    code += b"\x61"                                    # popad
    code += b"\xC3"                                    # ret
    return bytes(code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--fn", type=lambda v: int(v, 0), required=True,
                    help="client function VA to call")
    ap.add_argument("--arg", type=lambda v: int(v, 0), default=0,
                    help="dword pushed as the single argument")
    ap.add_argument("--ecx", type=lambda v: int(v, 0), default=None,
                    help="value loaded into ecx before the call (thiscall)")
    ap.add_argument("--blob", help="file whose bytes are copied into the page")
    ap.add_argument("--msg", action="store_true",
                    help="build a msg_t in-client and pass its address via ecx")
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args()

    h = k32.OpenProcess(PROCESS_ALL, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")

    payload = b""
    if args.blob:
        with open(args.blob, "rb") as fh:
            payload = fh.read()

    entry_size = ctypes.sizeof(Entry)
    msg_offset = entry_size + len(payload)
    msg_size = MSG_T_SIZE if args.msg else 0
    code_offset = msg_offset + msg_size + 0x10
    total = code_offset + 0x40

    remote = k32.VirtualAllocEx(h, None, total, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not remote:
        raise SystemExit(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
    base = remote
    payload_va = base + entry_size
    msg_va = base + msg_offset
    code_va = base + code_offset

    ecx = args.ecx
    push_value = args.arg
    msg = b""
    if args.msg:
        buf = bytearray(MSG_T_SIZE)
        struct.pack_into("<I", buf, 0x00, 0)              # allowoverflow
        struct.pack_into("<I", buf, 0x08, payload_va)     # data
        struct.pack_into("<I", buf, 0x10, len(payload))   # maxsize
        struct.pack_into("<I", buf, 0x14, 0)              # cursize
        struct.pack_into("<I", buf, 0x18, 0)              # readcount
        struct.pack_into("<I", buf, 0x2C, 0)              # oob
        msg = bytes(buf)
        ecx = msg_va
        push_value = 0

    code = build_code(args.fn, ecx, push_value, base)

    image = bytearray(total)
    image[0:entry_size] = struct.pack("<III", 0, args.fn, push_value)
    image[entry_size:entry_size + len(payload)] = payload
    if msg:
        image[msg_offset:msg_offset + msg_size] = msg
    image[code_offset:code_offset + len(code)] = code

    n = ctypes.c_size_t()
    if not k32.WriteProcessMemory(h, ctypes.c_void_p(base), bytes(image), total, ctypes.byref(n)):
        raise SystemExit(f"WriteProcessMemory failed: {ctypes.get_last_error()}")

    tid = W.DWORD()
    th = k32.CreateRemoteThread(h, None, 0, ctypes.c_void_p(code_va), None, 0, ctypes.byref(tid))
    if not th:
        raise SystemExit(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
    k32.WaitForSingleObject(th, int(args.timeout * 1000))
    k32.CloseHandle(th)

    buf = ctypes.create_string_buffer(ctypes.sizeof(Entry))
    if k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, ctypes.sizeof(Entry), ctypes.byref(n)):
        res, fn, arg = struct.unpack("<III", buf.raw)
        print(f"called {fn:#x}(ecx={None if ecx is None else hex(ecx)}, arg={arg:#x}) -> eax={res:#x}")
    else:
        print("ReadProcessMemory of result failed")

    k32.VirtualFreeEx(h, ctypes.c_void_p(base), 0, MEM_RELEASE)
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
