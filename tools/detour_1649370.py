"""Replace a 32-bit client function with a stub that fakes a received packet.

The client has no usable inbound transport, so instead of feeding a queue we
replace the engine's own ring reader with code that hands the consumer our
serialized server message.  `0x674FE0(client_idx, out)` normally copies one
packet from the per-client ring and returns 1 (or returns 0 when empty).  Our
stub fills `out` (out+0 = length, out+8 = data pointer) and returns 1, so the
engine's consumer `0x4F8C50` treats the payload as a freshly received packet.

The stub keeps the original frame shape (push ebp / mov ebp,esp / push ebx ...
pop ebx / pop ebp / ret) so the caller's stack stays balanced.

    python tools/detour_1649370.py --pid 1234 --fn 0x674FE0 --blob runs/gamestate-native.bin
    python tools/detour_1649370.py --pid 1234 --fn 0x674FE0 --blob runs/gamestate-native.bin --restore
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p

PROCESS_ALL = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_READ = 0x20

# Bytes we overwrite at the target: push ebp; mov ebp,esp; push ebx; mov ebx,[ebp+8]
STOLEN = 7


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--fn", type=lambda v: int(v, 0), required=True)
    ap.add_argument("--blob", help="payload file handed to the consumer")
    ap.add_argument("--restore", action="store_true", help="undo the detour")
    ap.add_argument("--length", type=lambda v: int(v, 0), default=None,
                    help="override the length written to out+0")
    args = ap.parse_args()

    h = k32.OpenProcess(PROCESS_ALL, False, args.pid)
    if not h:
        raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
    n = ctypes.c_size_t()

    def read(va: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(va), buf, size, ctypes.byref(n))
        return buf.raw if ok and n.value == size else None

    def write(va: int, blob: bytes) -> bool:
        old = W.DWORD()
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), 0x40, ctypes.byref(old))
        buf = ctypes.create_string_buffer(blob, len(blob))
        ok = k32.WriteProcessMemory(h, ctypes.c_void_p(va), buf, len(blob), ctypes.byref(n))
        k32.VirtualProtectEx(h, ctypes.c_void_p(va), len(blob), old.value, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(va), len(blob))
        return bool(ok) and n.value == len(blob)

    original = read(args.fn, STOLEN)
    if not original:
        raise SystemExit("cannot read target bytes")
    print(f"original: {original.hex(' ')}")

    if args.restore:
        ok = write(args.fn, original)
        print(f"restored={ok} bytes_after={read(args.fn, STOLEN).hex(' ')}")
        k32.CloseHandle(h)
        return 0

    payload = b""
    if args.blob:
        with open(args.blob, "rb") as fh:
            payload = fh.read()
    length = args.length if args.length is not None else len(payload)

    # cave layout: [payload][code]
    payload_size = len(payload)
    code_offset = payload_size + 0x10
    total = code_offset + 0x40

    cave = k32.VirtualAllocEx(h, None, total, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
    if not cave:
        raise SystemExit(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
    payload_va = cave
    code_va = cave + code_offset

    code = bytearray()
    code += b"\x55"                                  # push ebp
    code += b"\x8B\xEC"                              # mov ebp, esp
    code += b"\x53"                                  # push ebx
    code += b"\x8B\x4D\x0C"                          # mov ecx, [ebp+0xC]   (out struct)
    code += b"\xC7\x01" + struct.pack("<I", length & 0xFFFFFFFF)   # mov dword [ecx], length
    code += b"\xC7\x41\x08" + struct.pack("<I", payload_va)        # mov dword [ecx+8], payload
    code += b"\xB8\x01\x00\x00\x00"                  # mov eax, 1
    code += b"\x5B"                                  # pop ebx
    code += b"\x5D"                                  # pop ebp
    code += b"\xC3"                                  # ret

    image = bytearray(total)
    image[0:payload_size] = payload
    image[code_offset:code_offset + len(code)] = bytes(code)
    if not write(cave, bytes(image)):
        raise SystemExit("failed to write cave")

    detour = b"\xE9" + struct.pack("<I", code_va - (args.fn + 5))
    detour += b"\x90" * (STOLEN - len(detour))
    ok = write(args.fn, detour)
    print(f"detour_installed={ok} cave={cave:#x} code={code_va:#x} payload={payload_va:#x} len={length}")
    print(f"bytes_after={read(args.fn, STOLEN).hex(' ')}")

    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
