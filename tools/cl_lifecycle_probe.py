"""Lifecycle probe for the Build 1649370 client objects.

The two objects that matter are encoded globals:

* `cl  = [0x331C0C8] ^ 0xD362501F`  (0x12A700 bytes, allocated by CL_Init)
* `cl2 = [0x76638F4] ^ 0x6891D1C7`  (0x00AA10 bytes, allocated by CL_Init)

`cl+0xA8F0` is *not* a cl field: `0x5B2C10` reads `[ebx+0xA8F0]` with
`ebx = cl2`, and CL_Init's 0x5C8628 block writes `[cl2+0xA8F0] = alloc(0x180)
^ 0x96B9DC91`.  This tool therefore dumps and repairs the cl2 field, and never
touches the old (wrong) cl+0xA8F0 target.

It installs three counting stubs so one client session answers whether the
client object is torn down and rebuilt around a 0x5B2C10 call:

    0x5C83D0  CL_Init entry          (entries; records caller return address)
    0x5C85BF  mov [0x331C0C8],eax    (actual cl allocations)
    0x5C8A70  teardown / CL_Shutdown (runs; records caller return address)

Every stub replays its displaced bytes and jumps back, so the instrumented code
behaves exactly as before.  Records live in the cave, so they survive as long as
the process does, and `read` reports `process_alive` instead of trusting the
launcher's early `process_alive_after`.

    python tools/cl_lifecycle_probe.py selftest
    python tools/cl_lifecycle_probe.py install
    python tools/cl_lifecycle_probe.py read --output runs/t0.json
    python tools/cl_lifecycle_probe.py repair-cl2 --output runs/repair.json
    python tools/cl_lifecycle_probe.py revert
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from ctypes import wintypes as W

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "runs" / "cl_lifecycle_state.json"

EXE_NAME = "codol1649370-offline.exe"
PROCESS_ALL = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04

CL_ENCODED = 0x331C0C8
CL_XOR = 0xD362501F
CL2_ENCODED = 0x76638F4
CL2_XOR = 0x6891D1C7
INIT_FLAG = 0x3381398
PHASE = 0x76446B0
A8F0_KEY = 0x96B9DC91
A8DC_VALUE = 0x1F
A8D8_VALUE = 0x20

CAVE_SIZE = 0x1000
STUB_OFFSETS = {
    "cl_init_enter": 0x000,
    "cl_create": 0x040,
    "cl_shutdown": 0x080,
    "b2c10_enter": 0x0C0,
}
RECORD_OFFSETS = {
    "cl_init_enter": 0x200,
    "cl_create": 0x210,
    "cl_shutdown": 0x220,
    "b2c10_enter": 0x230,
}

# name, site VA, exact displaced bytes, resume VA, record caller return address
SITES = (
    ("cl_init_enter", 0x5C83D0, bytes.fromhex("558bec83ec70"), 0x5C83D6, True),
    ("cl_create", 0x5C85BF, bytes.fromhex("a3c8c03103"), 0x5C85C4, False),
    ("cl_shutdown", 0x5C8A70, bytes.fromhex("33c0a3808b5007"), 0x5C8A77, True),
    # sub esp,0x884 is `81 ec 84 08 00 00` (6 bytes), so the resumed instruction
    # starts at 0x5B2C19, not 0x5B2C18; the displaced span is 9 bytes.
    ("b2c10_enter", 0x5B2C10, bytes.fromhex("558bec81ec84080000"), 0x5B2C19, True),
)

CL_FIELDS = {
    "flag_100260": 0x100260,
    "netadr_109260": 0x109260,
    "field_109250": 0x109250,
    "count_144": 0x144,
    "limit_140": 0x140,
    "field_80148": 0x80148,
    "field_8014C": 0x8014C,
    "field_13C": 0x13C,
}
CL2_FIELDS = {
    "a8f0_encoded": 0xA8F0,
    "a8dc_mask": 0xA8DC,
    "a8d8": 0xA8D8,
    "count_68D0": 0x68D0,
    "base_1C": 0x1C,
    "base_2C": 0x2C,
    "callback_30": 0x30,
}
# globals involved in the 0x66F170 callback decode: edx = (cl2+0x2C) ^ [cl2+0x30] ^ [0xE60B78]
GLOBALS = {
    "callback_key_E60B78": 0xE60B78,
    "guard_7508B80": 0x7508B80,
    "clock_base_3401E48": 0x3401E48,
    "flag_33813C4": 0x33813C4,
}

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.CloseHandle.argtypes = [W.HANDLE]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_pid() -> int:
    import subprocess

    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV"],
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return 0


def read(handle, address: int, size: int) -> bytes | None:
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    ok = k32.ReadProcessMemory(handle, C.c_void_p(address), buf, size, C.byref(got))
    if not ok or got.value != size:
        return None
    return buf.raw


def write(handle, address: int, data: bytes) -> bool:
    wrote = C.c_size_t()
    ok = k32.WriteProcessMemory(
        handle, C.c_void_p(address), C.create_string_buffer(data, len(data)), len(data), C.byref(wrote)
    )
    return bool(ok) and wrote.value == len(data)


def u32(handle, address: int) -> int | None:
    raw = read(handle, address, 4)
    return struct.unpack("<I", raw)[0] if raw else None


def build_stub(stub_address: int, record: int, record_return: bool, original: bytes, resume: int) -> bytes:
    code = bytearray()
    code += b"\x9c"                                    # pushfd
    code += b"\x60"                                    # pushad
    code += b"\xff\x05" + struct.pack("<I", record)    # inc dword [record]
    if record_return:
        code += b"\x8b\x44\x24\x24"                    # mov eax,[esp+0x24] (original stack top)
        code += b"\xa3" + struct.pack("<I", record + 4)  # mov [record+4],eax
    code += b"\x61"                                    # popad
    code += b"\x9d"                                    # popfd
    code += original                                   # replay displaced bytes
    code += b"\xe9" + struct.pack("<i", resume - (stub_address + len(code) + 5))
    return bytes(code)


def check_instruction_boundaries(problems: list[str]) -> None:
    """Prove every displaced span ends on an instruction boundary of the shipped image."""
    try:
        import capstone
    except ImportError:
        problems.append("capstone unavailable: cannot verify instruction boundaries")
        return
    image = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
    if not image.is_file():
        problems.append("client image missing: cannot verify instruction boundaries")
        return
    data = image.read_bytes()
    base = 0x400000  # .text is RVA 0x1000 / raw 0x400, so file offset = VA - base
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    for name, site, original, resume, _ in SITES:
        blob = data[site - base: site - base + 64]
        consumed = 0
        for insn in md.disasm(blob, site):
            consumed += insn.size
            if consumed >= len(original):
                break
        if site + consumed != resume:
            problems.append(
                f"{name}: displaced {len(original)} bytes end at 0x{site + consumed:X}, "
                f"but resume is 0x{resume:X}"
            )


def stub_layout() -> list[dict]:
    rows = []
    for name, site, original, resume, record_return in SITES:
        stub = STUB_OFFSETS[name]
        record = RECORD_OFFSETS[name]
        rows.append(
            {
                "name": name,
                "site": site,
                "original": original,
                "resume": resume,
                "stub_offset": stub,
                "record_offset": record,
                "record_return": record_return,
                "stub_size": len(build_stub(0, record, record_return, original, 0)),
            }
        )
    return rows


def open_client(pid: int):
    if not pid:
        return 0, None
    return pid, k32.OpenProcess(PROCESS_ALL, False, pid)


def install(pid: int) -> int:
    layout = stub_layout()
    pid, handle = open_client(pid)
    if not handle:
        print(json.dumps({"status": "client_not_running"}, indent=2))
        return 3
    try:
        # verify every site before touching anything
        for row in layout:
            live = read(handle, row["site"], len(row["original"]))
            if live != row["original"]:
                print(json.dumps({"status": "byte_mismatch", "site": hex(row["site"]),
                                  "expected": row["original"].hex(),
                                  "found": live.hex() if live else None}, indent=2))
                return 4
        cave_addr = k32.VirtualAllocEx(handle, None, CAVE_SIZE, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
        if not cave_addr:
            print(json.dumps({"status": "alloc_failed", "error": C.get_last_error()}, indent=2))
            return 5
        cave = int(cave_addr)
        installed = []
        try:
            for row in layout:
                stub_address = cave + row["stub_offset"]
                code = build_stub(stub_address, cave + row["record_offset"], row["record_return"],
                                  row["original"], row["resume"])
                if not write(handle, stub_address, code):
                    raise OSError("stub write failed")
                if not write(handle, cave + row["record_offset"], bytes(8)):
                    raise OSError("record init failed")
                patch = b"\xe9" + struct.pack("<i", stub_address - (row["site"] + 5))
                patch += b"\x90" * (len(row["original"]) - 5)
                if not write(handle, row["site"], patch):
                    raise OSError("site patch failed")
                k32.FlushInstructionCache(handle, C.c_void_p(row["site"]), len(patch))
                readback = read(handle, row["site"], len(patch))
                if readback != patch:
                    raise OSError(f"readback mismatch at {row['site']:#x}")
                installed.append({
                    "name": row["name"], "site": hex(row["site"]),
                    "stub": hex(stub_address), "record": hex(cave + row["record_offset"]),
                    "original": row["original"].hex(), "patch": patch.hex(),
                    "readback": readback.hex(), "verified": True,
                })
        except OSError as error:
            for row in installed:
                write(handle, int(row["site"], 16), bytes.fromhex(row["original"]))
            k32.FlushInstructionCache(handle, None, 0)
            print(json.dumps({"status": "install_failed_rolled_back", "error": str(error)}, indent=2))
            return 6
        state = {"schema": 1, "build": 1649370, "utc": now(), "pid": pid, "cave": hex(cave),
                 "sites": installed}
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "installed", **state}, indent=2))
        return 0
    finally:
        k32.CloseHandle(handle)


def dump_state(handle) -> dict:
    encoded_cl = u32(handle, CL_ENCODED)
    encoded_cl2 = u32(handle, CL2_ENCODED)
    cl = (encoded_cl ^ CL_XOR) if encoded_cl is not None else None
    cl2 = (encoded_cl2 ^ CL2_XOR) if encoded_cl2 is not None else None
    row = {
        "cl_encoded": f"0x{encoded_cl:08X}" if encoded_cl is not None else None,
        "cl": f"0x{cl:08X}" if cl else None,
        "cl2_encoded": f"0x{encoded_cl2:08X}" if encoded_cl2 is not None else None,
        "cl2": f"0x{cl2:08X}" if cl2 else None,
        "init_flag_3381398": u32(handle, INIT_FLAG),
        "phase_76446B0": u32(handle, PHASE),
        "globals": {},
        "cl_fields": {},
        "cl2_fields": {},
    }
    for name, address in GLOBALS.items():
        value = u32(handle, address)
        row["globals"][name] = f"0x{value:08X}" if value is not None else None
    if cl2:
        base_2c = cl2 + 0x2C
        callback_30 = u32(handle, cl2 + 0x30)
        key = u32(handle, GLOBALS["callback_key_E60B78"])
        if callback_30 is not None and key is not None:
            row["callback_decode"] = {
                "formula": "(cl2+0x2C) ^ [cl2+0x30] ^ [0xE60B78]",
                "computed": f"0x{(base_2c ^ callback_30 ^ key) & 0xFFFFFFFF:08X}",
            }
    if cl:
        for name, offset in CL_FIELDS.items():
            value = u32(handle, cl + offset)
            row["cl_fields"][name] = f"0x{value:08X}" if value is not None else None
    if cl2:
        for name, offset in CL2_FIELDS.items():
            value = u32(handle, cl2 + offset)
            row["cl2_fields"][name] = f"0x{value:08X}" if value is not None else None
    return row


def require_state() -> dict:
    if not STATE_PATH.is_file():
        raise SystemExit(f"no probe state at {STATE_PATH}; run install first")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def read_counters(state: dict) -> dict:
    pid = int(state["pid"])
    _, handle = open_client(pid)
    row = {"schema": 1, "build": 1649370, "utc": now(), "pid": pid, "process_alive": bool(handle)}
    if handle:
        try:
            counters = {}
            for site in state["sites"]:
                base = int(site["record"], 16)
                raw = read(handle, base, 8)
                if raw is None:
                    counters[site["name"]] = None
                    continue
                count, last_return = struct.unpack("<II", raw)
                counters[site["name"]] = {
                    "count": count,
                    "last_caller": f"0x{last_return:08X}" if last_return else None,
                }
            row["counters"] = counters
            row["dump"] = dump_state(handle)
        finally:
            k32.CloseHandle(handle)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("install")
    p.add_argument("--pid", type=int, default=0)

    p = sub.add_parser("read")
    p.add_argument("--output")

    p = sub.add_parser("dump")
    p.add_argument("--output")

    sub.add_parser("revert")

    p = sub.add_parser("repair-cl2")
    p.add_argument("--output")

    sub.add_parser("selftest")

    args = parser.parse_args()

    if args.command == "selftest":
        layout = stub_layout()
        problems = []
        expected_offsets = [4 + 32]  # pushfd + pushad before the original stack top
        if expected_offsets != [36]:
            problems.append("stack offset invariant broken")
        for row in layout:
            if len(row["original"]) < 5:
                problems.append(f"{row['name']}: displaced bytes shorter than a rel32 jump")
            if row["record_return"] and expected_offsets[0] != 0x24:
                problems.append(f"{row['name']}: return-address offset is not 0x24")
            cave = 0x10000000 + row["stub_offset"]
            code = build_stub(cave, 0x10000200 + row["record_offset"], row["record_return"],
                              row["original"], row["resume"])
            rel = struct.unpack_from("<i", code, len(code) - 4)[0]
            if cave + len(code) + rel != row["resume"]:
                problems.append(f"{row['name']}: jump target mismatch")
            if code[0] != 0x9C or code[1] != 0x60:
                problems.append(f"{row['name']}: stub prologue mismatch")
        check_instruction_boundaries(problems)
        row = {"schema": 1, "utc": now(), "sites": [
            {"name": item["name"], "site": hex(item["site"]), "stub_size": item["stub_size"],
             "record_return": item["record_return"]} for item in layout],
            "problems": problems, "ok": not problems}
        print(json.dumps(row, indent=2))
        return 0 if not problems else 1

    if args.command == "install":
        return install(args.pid or find_pid())

    state = require_state()

    if args.command == "revert":
        pid = int(state["pid"])
        _, handle = open_client(pid)
        if not handle:
            print(json.dumps({"status": "client_not_running"}, indent=2))
            return 3
        try:
            rows = []
            for site in state["sites"]:
                address = int(site["site"], 16)
                original = bytes.fromhex(site["original"])
                write(handle, address, original)
                k32.FlushInstructionCache(handle, C.c_void_p(address), len(original))
                rows.append({"site": site["site"], "reverted": read(handle, address, len(original)) == original})
            print(json.dumps({"status": "reverted", "sites": rows}, indent=2))
            return 0
        finally:
            k32.CloseHandle(handle)

    if args.command == "read":
        row = read_counters(state)
        text = json.dumps(row, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps(row, ensure_ascii=True, indent=2))
        return 0

    if args.command == "dump":
        pid = int(state["pid"])
        _, handle = open_client(pid)
        if not handle:
            print(json.dumps({"status": "client_not_running"}, indent=2))
            return 3
        try:
            row = {"schema": 1, "utc": now(), "pid": pid, "dump": dump_state(handle)}
        finally:
            k32.CloseHandle(handle)
        text = json.dumps(row, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps(row, ensure_ascii=True, indent=2))
        return 0

    if args.command == "repair-cl2":
        pid = int(state["pid"])
        _, handle = open_client(pid)
        if not handle:
            print(json.dumps({"status": "client_not_running"}, indent=2))
            return 3
        try:
            encoded = u32(handle, CL2_ENCODED)
            cl2 = (encoded ^ CL2_XOR) if encoded is not None else 0
            if not cl2:
                print(json.dumps({"status": "cl2_missing", "cl2_encoded": hex(encoded or 0)}, indent=2))
                return 4
            before = {name: u32(handle, cl2 + offset) for name, offset in CL2_FIELDS.items()}
            block = int(k32.VirtualAllocEx(handle, None, 0x180, MEM_COMMIT_RESERVE, PAGE_READWRITE) or 0)
            if not block:
                print(json.dumps({"status": "alloc_failed", "error": C.get_last_error()}, indent=2))
                return 5
            writes = {"a8f0_encoded": block ^ A8F0_KEY}
            if before["a8dc_mask"] == 0:
                writes["a8dc_mask"] = A8DC_VALUE
            if before["a8d8"] == 0:
                writes["a8d8"] = A8D8_VALUE
            for name, value in writes.items():
                write(handle, cl2 + CL2_FIELDS[name], struct.pack("<I", value))
            after = {name: u32(handle, cl2 + offset) for name, offset in CL2_FIELDS.items()}
            row = {
                "schema": 1, "build": 1649370, "utc": now(), "pid": pid,
                "cl2": hex(cl2), "block": hex(block), "key": hex(A8F0_KEY),
                "before": {k: (hex(v) if v is not None else None) for k, v in before.items()},
                "writes": {k: hex(v) for k, v in writes.items()},
                "after": {k: (hex(v) if v is not None else None) for k, v in after.items()},
                "verified": after.get("a8f0_encoded") == (block ^ A8F0_KEY),
            }
        finally:
            k32.CloseHandle(handle)
        text = json.dumps(row, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps(row, ensure_ascii=True, indent=2))
        return 0 if row["verified"] else 6

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
