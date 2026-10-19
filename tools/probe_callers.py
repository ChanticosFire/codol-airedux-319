#!/usr/bin/env python
r"""Find direct call sites of a target VA in the running client.

Scans executable memory for ``E8 rel32`` instructions whose target equals the
requested VA, then disassembles a window around each candidate. This finds the
caller of a function when no absolute pointer to it exists (x86 direct calls
are relative). Read-only; terminated afterwards.

Example:
  python tools/probe_callers.py --client-dir runtime\client-1649370 \
      --evidence runs\<id>\callers.json --target 0xB986C0 --wait 6
"""

from __future__ import annotations

import argparse
import ctypes
import json
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--target", required=True, help="VA, e.g. 0xB986C0 or RVA via 0x79A6C0 with --base 0x400000")
    parser.add_argument("--base", type=lambda v: int(v, 0), default=0,
                        help="optional module base added to --target when it is an RVA")
    parser.add_argument("--wait", type=float, default=6.0)
    parser.add_argument("--game-args", default="-q")
    args = parser.parse_args()
    target = int(args.target, 0) + args.base
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
    record = {"build": BUILD, "pid": pid, "target": hex(target), "callers": [], "notes": ["direct E8 calls only"]}
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
            base = next((m["base"] for m in modules if m["name"].lower().startswith("codomp_client_shipretail.exe")), 0)
            record["module_base"] = hex(base)
            regions = probe.regions_of(process)
            md = Cs(CS_ARCH_X86, CS_MODE_32) if Cs else None
            for region in regions:
                if not (region["protect"] & 0x10 or region["protect"] & 0x20 or region["protect"] & 0x40):
                    continue
                data = probe.read_memory(process, region["base"], min(region["size"], 64 * 1024 * 1024))
                if not data:
                    continue
                cursor = 0
                while True:
                    index = data.find(b"\xE8", cursor)
                    if index < 0 or index + 5 > len(data):
                        break
                    cursor = index + 1
                    rel = int.from_bytes(data[index + 1:index + 5], "little", signed=True)
                    here = region["base"] + index
                    if here + 5 + rel == target:
                        candidate = {"call_site": hex(here), "region_base": hex(region["base"])}
                        if md:
                            code = probe.read_memory(process, here - 48, 128)
                            if code:
                                candidate["disassembly"] = [
                                    f"{ins.address:#010x} {ins.mnemonic} {ins.op_str}"
                                    for ins in md.disasm(code, here - 48)][:40]
                        record["callers"].append(candidate)
                        if len(record["callers"]) >= 40:
                            break
                if len(record["callers"]) >= 40:
                    break
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
