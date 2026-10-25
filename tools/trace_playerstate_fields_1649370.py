"""Record live player-state field reads without changing the parser result.

The hook is for the exact 1649370 image, at 0x6701D0. It records a bounded
ring of call-site and message-cursor data. Install while the client is running,
then dump the ring using the JSON file written at installation.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from pathlib import Path

import hook_any_1649370 as h

TARGET = 0x6701D0
ORIGINAL = bytes.fromhex("55 8b ec 83 ec 28")
CAPACITY = 4096
WORDS_PER_RECORD = 7
RECORD_BYTES = WORDS_PER_RECORD * 4


def open_process(pid: int):
    handle = h.k32.OpenProcess(0x1F0FFF, False, pid)
    if not handle:
        raise OSError(f"OpenProcess({pid}) failed: {C.get_last_error()}")
    return handle


def read(handle, address: int, count: int) -> bytes:
    buffer = C.create_string_buffer(count)
    got = C.c_size_t()
    ok = h.k32.ReadProcessMemory(handle, C.c_void_p(address), buffer, count, C.byref(got))
    if not ok or got.value != count:
        raise OSError(f"ReadProcessMemory({address:#x}) failed: {C.get_last_error()}")
    return buffer.raw


def write(handle, address: int, payload: bytes) -> None:
    old = h.W.DWORD()
    if not h.k32.VirtualProtectEx(handle, C.c_void_p(address), len(payload), 0x40, C.byref(old)):
        raise OSError(f"VirtualProtectEx({address:#x}) failed")
    try:
        got = C.c_size_t()
        ok = h.k32.WriteProcessMemory(handle, C.c_void_p(address), C.create_string_buffer(payload),
                                      len(payload), C.byref(got))
        if not ok or got.value != len(payload):
            raise OSError(f"WriteProcessMemory({address:#x}) failed: {C.get_last_error()}")
    finally:
        h.k32.VirtualProtectEx(handle, C.c_void_p(address), len(payload), old.value, C.byref(old))
    h.k32.FlushInstructionCache(handle, C.c_void_p(address), len(payload))


def build_stub(cave: int, buffer: int) -> bytes:
    count = buffer
    rows = buffer + 4
    code = bytearray()
    code += b"\x9c\x60"                           # pushfd; pushad
    code += b"\x8b\x05" + struct.pack("<I", count)  # mov eax,[count]
    code += b"\x89\xc2"                           # mov edx,eax
    code += b"\x81\xe2" + struct.pack("<I", CAPACITY - 1)  # and edx,mask
    code += b"\x6b\xd2" + bytes([RECORD_BYTES])    # imul edx,edx,28
    code += b"\xbf" + struct.pack("<I", rows)       # mov edi,rows
    code += b"\x01\xd7"                           # add edi,edx
    code += b"\x8b\x54\x24\x24"                 # mov edx,[esp+24h] return address
    code += b"\x89\x17"                           # [edi]=return
    code += b"\x8b\x74\x24\x28"                 # mov esi,[esp+28h] message pointer
    for src, dst in ((0x00, 0x04), (0x20, 0x08), (0x1C, 0x0C)):
        code += b"\x8b\x56" + bytes([src])         # mov edx,[esi+src]
        code += b"\x89\x57" + bytes([dst])         # mov [edi+dst],edx
    code += b"\x8b\x54\x24\x18\x89\x57\x10"  # saved ECX (field descriptor)
    code += b"\x8b\x54\x24\x14\x89\x57\x14"  # saved EDX (field offset)
    code += b"\x8b\x54\x24\x30\x89\x57\x18"  # arg2 (field index)
    code += b"\xff\x05" + struct.pack("<I", count) # inc count
    code += b"\x61\x9d"                           # popad; popfd
    code += ORIGINAL                               # replay prologue
    code += b"\xe9" + struct.pack("<i", TARGET + len(ORIGINAL) - (cave + len(code) + 5))
    return bytes(code)


def install(pid: int, output: Path) -> None:
    handle = open_process(pid)
    current = read(handle, TARGET, len(ORIGINAL))
    if current != ORIGINAL:
        raise RuntimeError(f"Unexpected bytes at {TARGET:#x}: {current.hex()}")
    buffer = int(h.k32.VirtualAllocEx(handle, None, 4 + CAPACITY * RECORD_BYTES, 0x3000, 0x40) or 0)
    cave = int(h.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40) or 0)
    if not buffer or not cave:
        raise OSError("VirtualAllocEx failed")
    stub = build_stub(cave, buffer)
    write(handle, buffer, bytes(4 + CAPACITY * RECORD_BYTES))
    write(handle, cave, stub)
    entry = b"\xe9" + struct.pack("<i", cave - (TARGET + 5)) + b"\x90"
    write(handle, TARGET, entry)
    if read(handle, TARGET, len(entry)) != entry:
        raise RuntimeError("Hook write verification failed")
    info = {"pid": pid, "target": hex(TARGET), "original": ORIGINAL.hex(),
            "entry": entry.hex(), "buffer": hex(buffer), "cave": hex(cave),
            "capacity": CAPACITY, "record_bytes": RECORD_BYTES, "stub": stub.hex()}
    output.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in info.items() if k != "stub"}, indent=2))


def dump(info_path: Path, output: Path) -> None:
    info = json.loads(info_path.read_text(encoding="utf-8"))
    handle = open_process(info["pid"])
    buffer = int(info["buffer"], 16)
    blob = read(handle, buffer, 4 + CAPACITY * RECORD_BYTES)
    count = struct.unpack_from("<I", blob)[0]
    keep = min(count, CAPACITY)
    start = count - keep
    records = []
    for index in range(start, count):
        offset = 4 + (index & (CAPACITY - 1)) * RECORD_BYTES
        ret, error, bit, cursor, descriptor, field_offset, field_index = struct.unpack_from("<7I", blob, offset)
        records.append({"sequence": index, "caller": hex(ret), "error": error,
                        "bit": bit, "cursor": cursor, "descriptor": hex(descriptor),
                        "field_offset": field_offset, "field_index": field_index})
    output.write_text(json.dumps({"info": str(info_path), "total_count": count,
                                  "records": records}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} records of {count} total to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ap_install = sub.add_parser("install")
    ap_install.add_argument("--pid", type=int, required=True)
    ap_install.add_argument("--output", type=Path, required=True)
    ap_dump = sub.add_parser("dump")
    ap_dump.add_argument("--info", type=Path, required=True)
    ap_dump.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "install":
        install(args.pid, args.output)
    else:
        dump(args.info, args.output)


if __name__ == "__main__":
    main()
