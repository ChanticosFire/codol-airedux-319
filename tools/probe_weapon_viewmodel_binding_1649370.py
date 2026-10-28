"""Probe or temporarily bind Build 1649370 weapon 78 to its loaded AK viewmodel.

This is a guarded client-memory diagnostic.  It does not change the server's
weapon data or establish a durable loading path.  A run-specific state file
allows the exact original pointer to be restored before closing the client.

    python tools/probe_weapon_viewmodel_binding_1649370.py --pid 1234
    python tools/probe_weapon_viewmodel_binding_1649370.py --pid 1234 --apply \
        --state runs/r759-viewmodel-binding.json
    python tools/probe_weapon_viewmodel_binding_1649370.py --pid 1234 \
        --restore-from runs/r759-viewmodel-binding.json
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
from pathlib import Path
from ctypes import wintypes as W

WEAPON_TABLE = 0x1988B50
VIEWMODEL_FIELD = 0x10
DEFAULT_AK47_MODEL = 0x2311A8C
PROCESS_ACCESS = 0x10 | 0x20 | 0x08  # VM_READ | VM_WRITE | VM_OPERATION

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.OpenProcess.restype = W.HANDLE
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                 C.POINTER(C.c_size_t)]
k32.ReadProcessMemory.restype = W.BOOL
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.restype = W.BOOL
k32.CloseHandle.argtypes = [W.HANDLE]


class ProcessMemory:
    def __init__(self, pid: int):
        self.pid = pid
        self.handle = k32.OpenProcess(PROCESS_ACCESS, False, pid)
        if not self.handle:
            raise OSError(C.get_last_error(), f"OpenProcess({pid})")

    def close(self) -> None:
        k32.CloseHandle(self.handle)

    def read(self, address: int, size: int) -> bytes:
        buffer = C.create_string_buffer(size)
        got = C.c_size_t()
        ok = k32.ReadProcessMemory(self.handle, C.c_void_p(address), buffer,
                                  size, C.byref(got))
        if not ok or got.value != size:
            raise OSError(C.get_last_error(), f"ReadProcessMemory({address:#x}, {size})")
        return buffer.raw

    def u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def name(self, xmodel_or_definition: int) -> str:
        name_address = self.u32(xmodel_or_definition)
        data = bytearray()
        for offset in range(0, 128, 16):
            chunk = self.read(name_address + offset, 16)
            if b"\0" in chunk:
                data.extend(chunk.split(b"\0", 1)[0])
                break
            data.extend(chunk)
        return data.decode("ascii", errors="replace")

    def write_u32(self, address: int, value: int) -> None:
        data = struct.pack("<I", value)
        wrote = C.c_size_t()
        ok = k32.WriteProcessMemory(self.handle, C.c_void_p(address), data,
                                    len(data), C.byref(wrote))
        if not ok or wrote.value != 4 or self.u32(address) != value:
            raise OSError(C.get_last_error(), f"WriteProcessMemory({address:#x})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--weapon-id", type=int, default=78)
    ap.add_argument("--model-address", type=lambda s: int(s, 0), default=DEFAULT_AK47_MODEL)
    ap.add_argument("--state", type=Path, help="ignored run-specific restore record for --apply")
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--restore-from", type=Path)
    args = ap.parse_args()
    if args.apply and args.state is None:
        ap.error("--apply requires --state")
    if not 0 <= args.weapon_id < 1200:
        ap.error("weapon ID out of observed table range")

    memory = ProcessMemory(args.pid)
    try:
        definition = memory.u32(WEAPON_TABLE + args.weapon_id * 4)
        if not definition:
            raise RuntimeError(f"weapon {args.weapon_id} is not registered")
        field = definition + VIEWMODEL_FIELD
        current = memory.u32(field)
        current_name = memory.name(current) if current else None
        weapon_name = memory.name(definition)
        result = {"pid": args.pid, "weapon_id": args.weapon_id,
                  "weapon_name": weapon_name, "definition": hex(definition),
                  "field": hex(field), "current": hex(current),
                  "current_model_name": current_name}
        if args.restore_from:
            saved = json.loads(args.restore_from.read_text(encoding="utf-8"))
            if (saved["pid"] != args.pid or saved["weapon_id"] != args.weapon_id
                    or saved["definition"] != hex(definition)
                    or saved["field"] != hex(field)):
                raise RuntimeError("restore record belongs to another client or weapon")
            original = int(saved["original"], 16)
            target = int(saved["target"], 16)
            if current == target:
                memory.write_u32(field, original)
            elif current != original:
                raise RuntimeError(f"unexpected current pointer {current:#x}; refusing restore")
            result.update(action="restore", restored=hex(memory.u32(field)))
        elif args.apply:
            if args.weapon_id != 78 or weapon_name != "ak47_mp" or current_name != "tag_origin":
                raise RuntimeError("expected AK-47 placeholder was not found; refusing write")
            model_name = memory.name(args.model_address)
            if model_name != "viewmodel_ak47":
                raise RuntimeError(f"target is {model_name!r}, not viewmodel_ak47")
            if args.state.exists():
                raise FileExistsError(f"restore record already exists: {args.state}")
            saved = {"pid": args.pid, "weapon_id": args.weapon_id,
                     "definition": hex(definition), "field": hex(field),
                     "original": hex(current), "target": hex(args.model_address),
                     "original_name": current_name, "target_name": model_name}
            args.state.parent.mkdir(parents=True, exist_ok=True)
            args.state.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
            memory.write_u32(field, args.model_address)
            result.update(action="apply", target=hex(args.model_address),
                          target_model_name=model_name, readback=hex(memory.u32(field)),
                          restore_record=str(args.state))
        else:
            result["action"] = "probe"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
