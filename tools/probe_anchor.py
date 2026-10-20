#!/usr/bin/env python
r"""Generic runtime anchor scanner for the staged 1649370 client.

Launches the client (default -q, Medium token suffices for early phases),
waits, then scans committed readable memory for caller-supplied byte anchors
(hex or ascii), records absolute 32-bit references inside executable regions
and disassembles around them.

Example:
  python tools/probe_anchor.py --client-dir runtime\client-1649370 \
      --evidence runs\<id>\anchor.json --wait 6 --anchor ascii:dwauth.ini \
      --anchor hex:d9a0e8 --dump-start 0x77C000 --dump-size 0x1000
"""

from __future__ import annotations

import argparse
import ctypes
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


def parse_anchor(spec: str) -> bytes:
    kind, _, value = spec.partition(":")
    if kind == "ascii":
        return value.encode("latin-1")
    if kind == "hex":
        return bytes.fromhex(value)
    raise SystemExit(f"bad anchor spec: {spec}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--wait", type=float, default=6.0)
    parser.add_argument("--anchor", action="append", default=[], help="ascii:TEXT or hex:BYTES")
    parser.add_argument("--dump-start", default="")
    parser.add_argument("--dump-size", type=lambda v: int(v, 0), default=0)
    parser.add_argument("--game-args", default="-q")
    args = parser.parse_args()
    anchors = [parse_anchor(spec) for spec in args.anchor]
    if not anchors:
        raise SystemExit("at least one --anchor is required")
    root = args.client_dir.resolve(strict=True)
    if root != (REPO_ROOT / "runtime" / "client-1649370").resolve():
        print("refusing: not the owned staged copy", file=sys.stderr)
        return 2
    checks = verify_client(root)
    if not all(check.ok for check in checks):
        print("refusing: anchor mismatch", file=sys.stderr)
        return 2
    exe = root / "codoMP_client_shipRetail.exe"
    command = f'"{exe}" {args.game_args}'
    si = probe.STARTUPINFOW(); si.cb = ctypes.sizeof(probe.STARTUPINFOW)
    pi = probe.PROCESS_INFORMATION()
    if not probe.k32.CreateProcessW(str(exe), ctypes.create_unicode_buffer(command), None, None, False,
                                    probe.CREATE_SUSPENDED | probe.CREATE_UNICODE_ENVIRONMENT, None, str(root),
                                    ctypes.byref(si), ctypes.byref(pi)):
        print("CreateProcessW failed", ctypes.get_last_error(), file=sys.stderr)
        return 2
    pid = pi.dwProcessId
    record = {"build": BUILD, "pid": pid, "command_line": command, "anchors": [], "notes": ["read-only scan"]}
    evidence = args.evidence.resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    try:
        probe.k32.ResumeThread(pi.hThread)
        time.sleep(args.wait)
        process = probe.k32.OpenProcess(probe.PROCESS_VM_READ | probe.PROCESS_QUERY_INFORMATION, False, pid)
        if not process:
            record["error"] = f"OpenProcess failed {ctypes.get_last_error()}"
            return 3
        try:
            modules = probe.modules_of(pid)
            record["modules"] = [{"name": m["name"], "base": hex(m["base"]), "size": m["size"]} for m in modules if m["base"]]
            regions = probe.regions_of(process)
            # Decrypted .tp3 pages can be PAGE_READWRITE (0x04), not only RX.
            executable = [r for r in regions
                          if r["protect"] & 0x10 or r["protect"] & 0x20
                          or r["protect"] & 0x40 or r["protect"] & 0x04]
            md = Cs(CS_ARCH_X86, CS_MODE_32) if Cs else None
            for anchor in anchors:
                hits = []
                for region in regions:
                    data = probe.read_memory(process, region["base"], min(region["size"], 64 * 1024 * 1024))
                    if not data:
                        continue
                    start = 0
                    while True:
                        index = data.find(anchor, start)
                        if index < 0:
                            break
                        start = index + 1
                        hits.append({"va": region["base"] + index, "protect": region["protect"],
                                     "region_base": region["base"]})
                entry = {"anchor": anchor.hex(), "hits": len(hits), "sites": []}
                for hit in hits[:40]:
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
                            if len(refs) >= 20:
                                break
                    site = {"va": hex(hit["va"]), "protect": hex(hit["protect"]),
                            "refs": [hex(v) for v in refs[:12]]}
                    if md and refs:
                        site["disassembly"] = []
                        for ref in refs[:4]:
                            code = probe.read_memory(process, ref - 32, 80)
                            if not code:
                                continue
                            site["disassembly"].append({"ref": hex(ref), "window": [
                                f"{ins.address:#010x} {ins.mnemonic} {ins.op_str}"
                                for ins in md.disasm(code, ref - 32)][:22]})
                    entry["sites"].append(site)
                record["anchors"].append(entry)
            if args.dump_start and args.dump_size:
                dump_start = int(args.dump_start, 0)
                dumped = probe.read_memory(process, dump_start, args.dump_size)
                if dumped:
                    record["dump"] = {"start": hex(dump_start), "size": len(dumped), "hex": dumped.hex()}
                    if md:
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
