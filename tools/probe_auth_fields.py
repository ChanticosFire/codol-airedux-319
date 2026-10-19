#!/usr/bin/env python
r"""Read-only runtime scan for the Auth JSON parser.

Starts the client with -q, lets it complete the /auth/ exchange, then scans
memory for the field-name strings found in the EXE data section and for
absolute 32-bit references to them. Produces candidate parser addresses.

Must run elevated: the client itself runs elevated (IIPS requires it), and
PROCESS_VM_READ on a higher-integrity process is denied otherwise.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from server319.manifest import BUILD, verify_client  # noqa: E402
import probe_no_tcls as probe  # noqa: E402

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
except ImportError:  # pragma: no cover
    Cs = None

ANCHORS = [b"lsg_server_ticket", b"server_ticket", b"auth_task", b"ciphertext",
           b"https://%s:%d/auth/", b"DW-Server-Ticket"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--wait", type=float, default=28.0)
    parser.add_argument("--extra-args", default="-q")
    parser.add_argument("--dump-start", default="0xB98000")
    parser.add_argument("--dump-size", type=lambda v: int(v, 0), default=0x3000)
    args = parser.parse_args()
    root = args.client_dir.resolve(strict=True)
    if root != (REPO_ROOT / "runtime" / "client-1649370").resolve():
        print("refusing: not the owned staged copy", file=sys.stderr)
        return 2
    checks = verify_client(root)
    if not all(check.ok for check in checks):
        print("refusing: anchor mismatch", file=sys.stderr)
        return 2
    exe = root / "codoMP_client_shipRetail.exe"
    command = f'"{exe}" -q'
    si = probe.STARTUPINFOW(); si.cb = ctypes.sizeof(probe.STARTUPINFOW)
    pi = probe.PROCESS_INFORMATION()
    if not probe.k32.CreateProcessW(str(exe), ctypes.create_unicode_buffer(command), None, None, False,
                                    probe.CREATE_SUSPENDED | probe.CREATE_UNICODE_ENVIRONMENT, None, str(root),
                                    ctypes.byref(si), ctypes.byref(pi)):
        print("CreateProcessW failed", ctypes.get_last_error(), file=sys.stderr)
        return 2
    pid = pi.dwProcessId
    record = {"build": BUILD, "pid": pid, "command_line": command, "anchors": [],
              "notes": ["read-only VM_READ scan after the Auth exchange"]}
    evidence = args.evidence.resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    try:
        probe.k32.ResumeThread(pi.hThread)
        time.sleep(args.wait)
        process = probe.k32.OpenProcess(probe.PROCESS_VM_READ | probe.PROCESS_QUERY_INFORMATION, False, pid)
        if not process:
            record["error"] = "OpenProcess failed"
            return 3
        try:
            modules = probe.modules_of(pid)
            record["modules"] = [{"name": m["name"], "base": hex(m["base"]), "size": m["size"]} for m in modules if m["base"]]
            regions = probe.regions_of(process)
            hits = []
            for region in regions:
                data = probe.read_memory(process, region["base"], min(region["size"], 64 * 1024 * 1024))
                if not data:
                    continue
                for anchor in ANCHORS:
                    start = 0
                    while True:
                        index = data.find(anchor, start)
                        if index < 0:
                            break
                        start = index + 1
                        hits.append({"anchor": anchor.decode(), "va": region["base"] + index,
                                     "region_base": region["base"], "protect": region["protect"]})
            executable = [r for r in regions if r["protect"] & 0x10 or r["protect"] & 0x20 or r["protect"] & 0x40]
            for hit in hits[:60]:
                needle = struct.pack("<I", hit["va"] & 0xFFFFFFFF)
                refs = []
                for region in executable:
                    data = probe.read_memory(process, region["base"], min(region["size"], 48 * 1024 * 1024))
                    if not data:
                        continue
                    start = 0
                    while True:
                        index = data.find(needle, start)
                        if index < 0:
                            break
                        start = index + 1
                        refs.append(region["base"] + index)
                        if len(refs) >= 30:
                            break
                hit["absolute_reference_count"] = len(refs)
                hit["absolute_reference_va"] = [hex(value) for value in refs[:15]]
                if Cs is not None and refs:
                    md = Cs(CS_ARCH_X86, CS_MODE_32)
                    windows = []
                    for ref in refs[:6]:
                        code = probe.read_memory(process, ref - 32, 80)
                        if not code:
                            continue
                        windows.append({"ref": hex(ref), "window": [
                            f"{ins.address:#010x} {ins.mnemonic} {ins.op_str}"
                            for ins in md.disasm(code, ref - 32)][:24]})
                    hit["disassembly"] = windows
                record["anchors"].append(hit)
            # Dump the Auth parser region so it can be disassembled offline.
            dump_start = int(args.dump_start, 0)
            dumped = probe.read_memory(process, dump_start, args.dump_size)
            if dumped:
                record["dump"] = {"start": hex(dump_start), "size": len(dumped), "hex": dumped.hex()}
                if Cs is not None:
                    md = Cs(CS_ARCH_X86, CS_MODE_32)
                    record["dump_disassembly"] = [
                        f"{ins.address:#010x} {ins.bytes.hex()} {ins.mnemonic} {ins.op_str}"
                        for ins in md.disasm(dumped, dump_start)][:4000]
        finally:
            probe.k32.CloseHandle(process)
    finally:
        handle = probe.k32.OpenProcess(probe.PROCESS_TERMINATE, False, pid)
        if handle:
            probe.k32.TerminateProcess(handle, 1)
            probe.k32.CloseHandle(handle)
        evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
