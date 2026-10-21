"""Minimal minidump reader for 32-bit (WOW64) thread contexts and stacks."""
from __future__ import annotations

import mmap
import struct
import sys
from pathlib import Path


class Dump:
    def __init__(self, path: str):
        self.f = open(path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        if self.m[:4] != b"MDMP":
            raise SystemExit("not a minidump")
        self.streams: dict[int, tuple[int, int]] = {}
        count = struct.unpack_from("<I", self.m, 8)[0]
        off = struct.unpack_from("<I", self.m, 12)[0]
        for i in range(count):
            typ, size, rva = struct.unpack_from("<III", self.m, off + i * 12)
            self.streams[typ] = (size, rva)
        self.ranges: list[tuple[int, int, int]] = []
        self._load_memory()

    def _load_memory(self) -> None:
        if 9 in self.streams:  # Memory64ListStream
            _, rva = self.streams[9]
            n = struct.unpack_from("<Q", self.m, rva)[0]
            base = struct.unpack_from("<Q", self.m, rva + 8)[0]
            p = rva + 16
            for _ in range(n):
                start, size = struct.unpack_from("<QQ", self.m, p)
                self.ranges.append((start, size, base))
                base += size
                p += 16
        elif 5 in self.streams:  # MemoryListStream
            _, rva = self.streams[5]
            n = struct.unpack_from("<I", self.m, rva)[0]
            p = rva + 4
            for _ in range(n):
                start, size, mrva = struct.unpack_from("<QII", self.m, p)
                self.ranges.append((start, size, mrva))
                p += 16

    def read(self, va: int, size: int) -> bytes | None:
        for start, length, rva in self.ranges:
            if start <= va and va + size <= start + length:
                return self.m[rva + (va - start): rva + (va - start) + size]
        return None

    def u32(self, va: int) -> int | None:
        b = self.read(va, 4)
        return struct.unpack("<I", b)[0] if b else None

    def threads(self):
        _, rva = self.streams[3]
        n = struct.unpack_from("<I", self.m, rva)[0]
        p = rva + 4
        for _ in range(n):
            tid, susp, pc, pri, teb, stack_start = struct.unpack_from("<IIIIQQ", self.m, p)
            stack_size, stack_rva, ctx_size, ctx_rva = struct.unpack_from("<IIII", self.m, p + 32)
            yield {
                "tid": tid, "teb": teb, "stack_start": stack_start,
                "stack_size": stack_size, "ctx_rva": ctx_rva, "ctx_size": ctx_size,
            }
            p += 48

    def context(self, ctx_rva: int) -> dict[str, int]:
        c = self.m[ctx_rva: ctx_rva + 716]
        flags = struct.unpack_from("<I", c, 0)[0]
        return {
            "flags": flags,
            "edi": struct.unpack_from("<I", c, 156)[0], "esi": struct.unpack_from("<I", c, 160)[0],
            "ebx": struct.unpack_from("<I", c, 164)[0], "edx": struct.unpack_from("<I", c, 168)[0],
            "ecx": struct.unpack_from("<I", c, 172)[0], "eax": struct.unpack_from("<I", c, 176)[0],
            "ebp": struct.unpack_from("<I", c, 180)[0], "eip": struct.unpack_from("<I", c, 184)[0],
            "esp": struct.unpack_from("<I", c, 196)[0],
        }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: parse_minidump_threads.py dump.dmp")
        return 2
    d = Dump(sys.argv[1])
    print("ranges", len(d.ranges), "threads stream", 3 in d.streams)
    for t in d.threads():
        c = d.context(t["ctx_rva"])
        print(f"\nTID {t['tid']} EIP={c['eip']:08x} ESP={c['esp']:08x} EBP={c['ebp']:08x} "
              f"EAX={c['eax']:08x} ECX={c['ecx']:08x} EDX={c['edx']:08x}")
        code = d.read(c["eip"], 24)
        print("  code:", code.hex() if code else "?")
        esp = c["esp"]
        stack = d.read(esp, 64)
        if stack:
            vals = struct.unpack("<16I", stack)
            print("  stack:", " ".join(f"{v:08x}" for v in vals))
        # EBP chain
        ebp = c["ebp"]
        for i in range(6):
            nxt = d.u32(ebp)
            ret = d.u32(ebp + 4) if ebp else None
            if not nxt or not ret:
                break
            print(f"  frame{i}: ret={ret:08x} ebp={ebp:08x}")
            if nxt <= ebp:
                break
            ebp = nxt
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
