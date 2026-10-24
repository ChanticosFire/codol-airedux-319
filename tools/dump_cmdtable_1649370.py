"""Recover CODOL's Cbuf command table at runtime and list every registered command.

The engine keeps a singly linked list per command:

    struct cmd_function_s {
        cmd_function_s *next;    // +0x00
        const char    *name;     // +0x04
        const char    *desc;     // +0x08
        xcommand_t     func;     // +0x0C
    };

(older idTech titles may drop `desc`, so the layout is probed rather than assumed)

We locate one entry by scanning for a pointer to a known command-name string
(default "vid_restart"), then walk `next` and print every name.  This gives the
exact set of commands this build accepts - which is what decides whether the
client can start a match by itself.

    python tools/dump_cmdtable_1649370.py
    python tools/dump_cmdtable_1649370.py --needle vid_restart --filter map
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import subprocess
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t]
k32.VirtualQueryEx.restype = C.c_size_t
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]

MEM_COMMIT = 0x1000
PAGE_READABLE = {0x02, 0x04, 0x20, 0x40, 0x80}   # READONLY / READWRITE / EXECUTE_READ / ...


class MEMORY_BASIC_INFORMATION(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("RegionSize", C.c_size_t),
                ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def find_pid() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq codol1649370-offline.exe", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit("client not running")


class Reader:
    def __init__(self, pid: int):
        self.handle = k32.OpenProcess(0x1F0FFF, False, pid)
        if not self.handle:
            raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")
        self.pid = pid

    def read(self, va: int, size: int) -> bytes | None:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(self.handle, C.c_void_p(va), buf, size, C.byref(got)) or got.value != size:
            return None
        return buf.raw

    def u32(self, va: int) -> int | None:
        data = self.read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    def cstr(self, va: int, limit: int = 96) -> str | None:
        data = self.read(va, limit)
        if not data:
            return None
        end = data.find(b"\0")
        if end <= 0:
            return None
        try:
            text = data[:end].decode("ascii")
        except UnicodeDecodeError:
            return None
        return text if all(32 <= ord(ch) < 127 for ch in text) else None

    def regions(self):
        address = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while address < 0x7FFF0000:
            got = k32.VirtualQueryEx(self.handle, C.c_void_p(address), C.byref(mbi), C.sizeof(mbi))
            if not got:
                break
            base = int(mbi.BaseAddress or 0)
            size = int(mbi.RegionSize)
            if size <= 0:
                break
            if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in PAGE_READABLE and size <= 0x10000000:
                yield base, size
            address = base + size

    def find_u32(self, value: int, limit: int = 64) -> list[int]:
        needle = struct.pack("<I", value)
        hits: list[int] = []
        for base, size in self.regions():
            data = self.read(base, size)
            if not data:
                continue
            pos = 0
            while True:
                index = data.find(needle, pos)
                if index < 0:
                    break
                if index % 4 == 0:
                    hits.append(base + index)
                    if len(hits) >= limit:
                        return hits
                pos = index + 1
        return hits


def string_address(exe: str, needle: bytes) -> int | None:
    import pefile
    pe = pefile.PE(exe, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    blob = open(exe, "rb").read()
    for section in pe.sections:
        raw = blob[section.PointerToRawData:section.PointerToRawData + section.SizeOfRawData]
        index = raw.find(needle + b"\0")
        if index >= 0:
            return base + section.VirtualAddress + index
    return None


def walk(reader: Reader, entry: int, layout: tuple[int, int], limit: int = 4000) -> list[dict]:
    """layout = (next_offset, name_offset)"""
    next_off, name_off = layout
    out: list[dict] = []
    seen: set[int] = set()
    cursor = entry
    while cursor and cursor not in seen and len(out) < limit:
        seen.add(cursor)
        name_ptr = reader.u32(cursor + name_off)
        if not name_ptr:
            break
        name = reader.cstr(name_ptr)
        if not name:
            break
        out.append({"entry": hex(cursor), "name": name, "func": hex(reader.u32(cursor + name_off + 4) or 0)})
        cursor = reader.u32(cursor + next_off) or 0
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--needle", default="vid_restart")
    ap.add_argument("--filter", default="")
    ap.add_argument("--limit", type=int, default=4000)
    ap.add_argument("--exe", default=r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    reader = Reader(pid)
    target = string_address(args.exe, args.needle.encode("ascii"))
    if not target:
        raise SystemExit(f"string {args.needle!r} not found in image")
    hits = reader.find_u32(target, limit=32)
    report: dict = {"pid": pid, "needle": args.needle, "string_va": hex(target), "hits": len(hits)}

    attempts = []
    for hit in hits[:8]:
        for layout in ((0, 4), (4, 8)):
            entry = hit - layout[1]
            names = walk(reader, entry, layout, limit=args.limit)
            if names:
                attempts.append({"layout": layout, "entry": hex(entry), "count": len(names),
                                 "sample": [n["name"] for n in names[:12]], "names": names})
    attempts.sort(key=lambda a: a["count"], reverse=True)
    report["attempts"] = [{k: v for k, v in a.items() if k != "names"} for a in attempts]

    if attempts:
        best = attempts[0]
        names = best["names"]
        report["best_layout"] = best["layout"]
        report["command_count"] = len(names)
        if args.filter:
            report["filtered"] = [n["name"] for n in names if args.filter.lower() in n["name"].lower()]
        out = f"runs/cmdtable-{args.needle}.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"string_va": report["string_va"], "layout": best["layout"],
                       "count": len(names), "commands": names}, fh, ensure_ascii=False, indent=1)
        report["dump"] = out
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
