"""Ring-buffer hook: record every first stack argument of a 1649370 function.

`hook_any_1649370.py` keeps only the latest call, so polling from Python misses
almost every call during the dense asset-loading window (measured: 99.8% of
0x661B80's calls).  This variant records each call's arg0 into a fixed ring in
the injected stub, so a single read of the ring afterwards recovers the whole
window instead of a sample.

    python tools/hook_ring_1649370.py --pid 1234 --target 0x661b80 --install
    python tools/hook_ring_1649370.py --pid 1234 --target 0x661b80 --read
    python tools/hook_ring_1649370.py --pid 1234 --target 0x661b80 --restore --original-hex ...
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from ctypes import wintypes as W
from pathlib import Path

import capstone

ROOT = Path(__file__).resolve().parents[1]
MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
MD.detail = False

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                   C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD,
                                 C.POINTER(W.DWORD)]
k32.VirtualProtectEx.restype = W.BOOL
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.FlushInstructionCache.restype = W.BOOL

DEFAULT_ENTRIES = 4096


def aligned_length(blob: bytes, start_va: int, minimum: int = 5) -> int:
    total = 0
    for ins in MD.disasm(blob, start_va):
        total += ins.size
        if total >= minimum:
            return total
    return minimum


def slot_base(target: int) -> int:
    return 0xE540000 + ((target >> 4) & 0xFFF0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--target", type=lambda text: int(text, 0), required=True)
    ap.add_argument("--entries", type=int, default=DEFAULT_ENTRIES)
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--original-hex", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    handle = k32.OpenProcess(0x1F0FFF, False, args.pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed err={C.get_last_error()}")
    state_path = ROOT / "runs" / f"ring-{args.target:x}.json"

    def read(va: int, size: int):
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buf, size, C.byref(got)):
            return None
        return buf.raw[:got.value]

    def write(va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        return bool(k32.WriteProcessMemory(handle, C.c_void_p(va),
                                          C.create_string_buffer(blob, len(blob)),
                                          len(blob), C.byref(got))) and got.value == len(blob)

    head = read(args.target, 16) or b""
    length = aligned_length(head, args.target, 5)
    entry = read(args.target, 5) or b""

    if args.read:
        if not state_path.is_file():
            raise SystemExit("no ring state; install first")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        ring = int(state["ring"], 16)
        head_va = int(state["head"], 16)
        mask = state["mask"]
        raw_head = read(head_va, 4)
        count = struct.unpack("<I", raw_head)[0] if raw_head else 0
        blob = read(ring, args.entries * 4) or b""
        values = []
        for index in range(0, len(blob) - 3, 4):
            values.append(struct.unpack_from("<I", blob, index)[0])
        unique = []
        seen = set()
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            text = read(value, 80)
            name = text.split(b"\x00")[0].decode("latin-1", "replace") if text else ""
            unique.append({"arg0": hex(value), "name": name})
        report = {"pid": args.pid, "target": hex(args.target), "head": count,
                  "mask": mask, "entries_read": len(values),
                  "unique_pointers": len(unique), "names": unique[:4000]}
        text = json.dumps(report, ensure_ascii=False, indent=1)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({k: report[k] for k in
                          ("target", "head", "entries_read", "unique_pointers")}, indent=1))
        print("\n".join(sorted({item["name"] for item in unique if item["name"]})[:400]))
        k32.CloseHandle(handle)
        return 0

    if args.restore:
        original = None
        if args.original_hex:
            original = bytes.fromhex(args.original_hex)
        elif state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            original = bytes.fromhex(state["original"])
        if not original:
            raise SystemExit("cannot restore without --original-hex or saved state")
        old = W.DWORD()
        k32.VirtualProtectEx(handle, C.c_void_p(args.target), len(original), 0x40, C.byref(old))
        ok = write(args.target, original)
        k32.VirtualProtectEx(handle, C.c_void_p(args.target), len(original), old.value,
                             C.byref(old))
        k32.FlushInstructionCache(handle, C.c_void_p(args.target), len(original))
        print(json.dumps({"restored": ok,
                          "bytes_after": (read(args.target, len(original)) or b"").hex()}))
        k32.CloseHandle(handle)
        return 0 if ok else 1

    if not args.install:
        raise SystemExit("choose --install, --read or --restore")

    if entry and entry[0] == 0xE9:
        raise SystemExit("target already holds a jump; restore it first")
    original = read(args.target, length)
    if not original:
        raise SystemExit("cannot read original bytes")
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    ring = int(k32.VirtualAllocEx(handle, None, max(args.entries * 4, 0x1000), 0x3000, 0x04) or 0)
    head_va = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x04) or 0)
    if not (cave and ring and head_va):
        raise SystemExit("VirtualAllocEx failed")
    mask = args.entries - 1
    code = bytearray()
    code += b"\x60"                                       # pushad
    code += b"\x8B\x44\x24\x24"                           # mov eax,[esp+0x24] arg0
    code += b"\x8B\x15" + struct.pack("<I", head_va)      # mov edx,[head]
    code += b"\x8B\xCA"                                   # mov ecx,edx
    code += b"\xC1\xE1\x02"                               # shl ecx,2
    code += b"\x81\xC1" + struct.pack("<I", ring)         # add ecx,ring
    code += b"\x89\x01"                                   # mov [ecx],eax
    code += b"\x42"                                       # inc edx
    code += b"\x81\xE2" + struct.pack("<I", mask)         # and edx,mask
    code += b"\x89\x15" + struct.pack("<I", head_va)      # mov [head],edx
    code += b"\x61"                                       # popad
    replay_addr = cave + len(code)
    replay = bytearray()
    for ins in MD.disasm(bytes(original), args.target):
        here = replay_addr + len(replay)
        raw = bytes(ins.bytes)
        if ins.mnemonic in ("call", "jmp") and ins.size == 5:
            tgt = int(ins.op_str, 16)
            replay += raw[:1] + struct.pack("<I", (tgt - (here + 5)) & 0xFFFFFFFF)
        elif ins.mnemonic.startswith("j") and ins.size == 6 and raw[0] == 0x0F:
            tgt = int(ins.op_str, 16)
            replay += raw[:2] + struct.pack("<I", (tgt - (here + 6)) & 0xFFFFFFFF)
        elif ins.mnemonic.startswith("j") and ins.size == 2:
            tgt = int(ins.op_str, 16)
            if ins.mnemonic == "jmp":
                replay += b"\xE9" + struct.pack("<I", (tgt - (here + 5)) & 0xFFFFFFFF)
            else:
                replay += bytes([0x0F, 0x80 + (raw[0] - 0x70)]) + \
                    struct.pack("<I", (tgt - (here + 6)) & 0xFFFFFFFF)
        else:
            replay += raw
    code += bytes(replay)
    rel = (args.target + length - (cave + len(code) + 5)) & 0xFFFFFFFF
    code += b"\xE9" + struct.pack("<I", rel)
    if not write(cave, bytes(code)):
        raise SystemExit("write cave failed")
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), length, 0x40, C.byref(old))
    jump = b"\xE9" + struct.pack("<I", (cave - (args.target + 5)) & 0xFFFFFFFF)
    jump += b"\x90" * (length - 5)
    hooked = write(args.target, jump)
    k32.VirtualProtectEx(handle, C.c_void_p(args.target), length, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(args.target), length)
    state = {"pid": args.pid, "target": hex(args.target), "length": length,
             "original": original.hex(), "cave": hex(cave), "ring": hex(ring),
             "head": hex(head_va), "entries": args.entries, "mask": mask,
             "hooked": hooked}
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(json.dumps(state, indent=1))
    k32.CloseHandle(handle)
    return 0 if hooked else 1


if __name__ == "__main__":
    raise SystemExit(main())
