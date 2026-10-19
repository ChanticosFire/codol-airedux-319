#!/usr/bin/env python
r"""Generic runtime patcher for the staged 1649370 client.

Launches the client with the given switches, waits for the unpacked code, then
applies one or more byte patches inside the process image only. Every patch is
verified against its expected original bytes first; a mismatch aborts that
patch (and is recorded). Terminating the process restores the on-disk copy.

Patch spec: ``RVA:HEXBYTES[:EXPECTED_HEX]`` e.g.
  --patch 0x7804F2:9090909090
  --patch 0x79A78E:9090:74B2

Runs at the same integrity as the client: Medium patches a Medium process,
elevated patches an elevated one.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from server319.manifest import BUILD, verify_client  # noqa: E402
import probe_no_tcls as probe  # noqa: E402
import launch_synthetic_tcls as launcher  # noqa: E402

PAGE_EXECUTE_READWRITE = 0x40
k32 = probe.k32
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                 wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.VirtualProtectEx.restype = wt.BOOL
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.restype = wt.BOOL


def parse_patch(spec: str) -> dict:
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise SystemExit(f"bad patch spec: {spec}")
    rva = int(parts[0], 0)
    new = bytes.fromhex(parts[1])
    expected = bytes.fromhex(parts[2]) if len(parts) == 3 else None
    if not new:
        raise SystemExit(f"empty patch: {spec}")
    return {"rva": rva, "new": new, "expected": expected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--patch", action="append", default=[], help="RVA:HEX[:EXPECTED]")
    parser.add_argument("--wait", type=float, default=7.0)
    parser.add_argument("--observe", type=float, default=40.0)
    parser.add_argument("--game-args", default="-q")
    parser.add_argument("--dismiss-dialogs", action="store_true")
    args = parser.parse_args()
    patches = [parse_patch(spec) for spec in args.patch]
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
    dismissed: set[int] = set()
    record = {"build": BUILD, "pid": pid, "command_line": command, "patches": [],
              "events": [], "notes": ["runtime-only patches; on-disk client unchanged"]}
    evidence = args.evidence.resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        probe.k32.ResumeThread(pi.hThread)
        time.sleep(args.wait)
        modules = probe.modules_of(pid)
        main_module = next((m for m in modules if m["name"].lower().startswith("codomp_client_shipretail.exe")), None)
        if not main_module:
            record["error"] = "main module not found"
            return 3
        base = main_module["base"]
        process = probe.k32.OpenProcess(
            probe.PROCESS_VM_READ | probe.PROCESS_QUERY_INFORMATION | 0x0020 | 0x0008, False, pid)
        if not process:
            record["error"] = f"OpenProcess failed {ctypes.get_last_error()}"
            return 3
        for spec in patches:
            va = base + spec["rva"]
            original = probe.read_memory(process, va, len(spec["new"]))
            entry = {"rva": hex(spec["rva"]), "va": hex(va),
                     "original": original.hex() if original else None,
                     "expected": spec["expected"].hex() if spec["expected"] else None,
                     "replacement": spec["new"].hex()}
            if spec["expected"] is not None and original != spec["expected"]:
                entry["applied"] = False
                entry["reason"] = "original bytes mismatch"
                record["patches"].append(entry)
                continue
            old_protect = wt.DWORD(0)
            if not k32.VirtualProtectEx(process, ctypes.c_void_p(va), len(spec["new"]),
                                        PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)):
                entry["applied"] = False
                entry["reason"] = f"VirtualProtectEx {ctypes.get_last_error()}"
                record["patches"].append(entry)
                continue
            written = ctypes.c_size_t(0)
            ok = k32.WriteProcessMemory(process, ctypes.c_void_p(va), spec["new"],
                                        len(spec["new"]), ctypes.byref(written))
            k32.VirtualProtectEx(process, ctypes.c_void_p(va), len(spec["new"]),
                                 old_protect.value, ctypes.byref(old_protect))
            entry["applied"] = bool(ok) and written.value == len(spec["new"])
            entry["verified_after"] = (probe.read_memory(process, va, len(spec["new"])) == spec["new"])
            record["patches"].append(entry)
            record["events"].append({"event": "patched", "rva": hex(spec["rva"]),
                                     "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        deadline = time.time() + args.observe
        try:
            while time.time() < deadline:
                time.sleep(1.0)
                alive, exit_code = launcher.process_alive(pid)
                rows = [row for row in launcher.tcp_rows() if row["pid"] == pid]
                if args.dismiss_dialogs:
                    launcher.dismiss_dialogs({pid}, dismissed, record["events"])
                record["events"].append({"event": "sample", "alive": alive, "exit_code": exit_code,
                                         "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                         "tcp": rows, "windows": launcher.windows_of({pid})})
                if not alive:
                    break
        except Exception as exc:
            record["events"].append({"event": "observe_error", "error": type(exc).__name__,
                                     "detail": str(exc)[:200]})
    finally:
        if process:
            probe.k32.CloseHandle(process)
        handle = probe.k32.OpenProcess(probe.PROCESS_TERMINATE, False, pid)
        if handle:
            probe.k32.TerminateProcess(handle, 1)
            probe.k32.CloseHandle(handle)
        evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
