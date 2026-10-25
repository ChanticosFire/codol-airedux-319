"""Locate ws2_32 in a live 32-bit client and report its send/recv entry points.

ASLR moves ws2_32 on every launch, so the addresses must be re-discovered each
run.  This walks the client's committed PE images with VirtualQueryEx (the
toolhelp module list is incomplete for this process) and resolves the wanted
exports from each image's export directory.

    python tools/find_ws2_1649370.py --pid 1234
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes as W

TARGETS = ("WSASendTo", "WSARecvFrom", "sendto", "recvfrom", "send", "recv")


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", W.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


class Client:
    def __init__(self, pid: int) -> None:
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.restype = W.HANDLE
        self.pid = pid
        self.h = self.k.OpenProcess(0x438, False, pid)
        if not self.h:
            raise SystemExit(f"OpenProcess failed: {ctypes.get_last_error()}")
        self.n = ctypes.c_size_t()

    def read(self, va: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        ok = self.k.ReadProcessMemory(self.h, ctypes.c_void_p(va), buf, size,
                                      ctypes.byref(self.n))
        return buf.raw if ok and self.n.value == size else None

    def u32(self, va: int) -> int | None:
        blob = self.read(va, 4)
        return struct.unpack("<I", blob)[0] if blob else None

    def images(self) -> list[int]:
        out: list[int] = []
        addr = 0x10000
        while addr < 0x7FFF0000:
            mbi = MBI()
            if not self.k.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi),
                                         ctypes.sizeof(mbi)):
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize or 0
            if mbi.Type == 0x1000000 and size:
                hdr = self.read(base, 0x1000)
                if hdr and hdr[:2] == b"MZ":
                    pe = struct.unpack_from("<I", hdr, 0x3C)[0]
                    if pe + 0x18 < len(hdr) and hdr[pe:pe + 4] == b"PE\x00\x00":
                        out.append(base)
            addr = base + size if size else addr + 0x1000
        return out

    def exports(self, base: int) -> dict[str, int]:
        hdr = self.read(base, 0x2000)
        if not hdr:
            return {}
        pe = struct.unpack_from("<I", hdr, 0x3C)[0]
        opts = pe + 24
        exp_rva = struct.unpack_from("<I", hdr, opts + 96)[0]
        exp_sz = struct.unpack_from("<I", hdr, opts + 100)[0]
        if not exp_rva or exp_sz < 40:
            return {}
        ne = self.read(base + exp_rva, 40)
        if not ne or len(ne) < 40:
            return {}
        nnames = struct.unpack_from("<I", ne, 24)[0]
        funcs_rva = struct.unpack_from("<I", ne, 28)[0]
        names_rva = struct.unpack_from("<I", ne, 32)[0]
        ords_rva = struct.unpack_from("<I", ne, 36)[0]
        if not nnames or not names_rva or not funcs_rva or not ords_rva:
            return {}
        count = min(nnames, 8000)
        names_blob = self.read(base + names_rva, count * 4)
        ords_blob = self.read(base + ords_rva, count * 2)
        if not names_blob or not ords_blob:
            return {}
        found: dict[str, int] = {}
        for i in range(count):
            rva = struct.unpack_from("<I", names_blob, i * 4)[0]
            raw = self.read(base + rva, 32)
            if not raw:
                continue
            name = raw.split(b"\x00")[0].decode("latin-1", "replace")
            if name not in TARGETS or name in found:
                continue
            ordinal = struct.unpack_from("<H", ords_blob, i * 2)[0]
            func_rva = self.u32(base + funcs_rva + ordinal * 4)
            if func_rva:
                found[name] = base + func_rva
        return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    args = ap.parse_args()

    client = Client(args.pid)
    for base in client.images():
        found = client.exports(base)
        if found:
            print(f"base={base:#010x}")
            for name in TARGETS:
                if name in found:
                    print(f"  {name:<12} {found[name]:#010x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
