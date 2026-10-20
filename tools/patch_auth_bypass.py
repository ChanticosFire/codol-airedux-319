#!/usr/bin/env python
r"""Runtime diagnostic patch: bypass the Auth ticket gate for Build 1649370.

The Auth JSON parser at RVA 0x79A78E tests the virtual ticket-verification
result and jumps to the failure path with the byte pattern ``74 B2`` (je).
That pattern is byte-identical to the 1604220 reference patch
(``0x79A70E: 74 B2 -> 90 90``); on 1649370 the same gate sits at
``0x79A78E`` because the code grew by 0x80.

This tool starts the client with -q, waits until the Auth exchange has run,
verifies the original bytes, flips them to NOP NOP via VirtualProtectEx, and
records everything. The patch lives only in the process image: terminating the
process restores the on-disk copy, so no client file is modified.

Must run elevated because the client runs elevated.
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
import launch_synthetic_tcls as launcher  # noqa: E402

PATCH_RVA = 0x79A78E
PATCH_ORIGINAL = b"\x74\xB2"   # je 0xB9A742
PATCH_REPLACEMENT = b"\x90\x90"  # nop nop
PAGE_EXECUTE_READWRITE = 0x40


def sample_lobby(process, base):
    """Read candidates from the patched process; failed reads stay null.

    Global addresses come from the prior 1649370 probes/1604220 reference.
    Their semantic interpretation remains provisional until traced here.
    """
    def read(address, size=4):
        raw = probe.read_memory(process, address, size)
        return int.from_bytes(raw, "little") if raw and len(raw) == size else None

    def global_value(va, size=4):
        return read(base + va - 0x400000, size)

    net = global_value(0x8269774)
    state_ptr = global_value(0xE4EA3C)
    state_raw = probe.read_memory(process, state_ptr, 80) if state_ptr else None
    auth_obj = global_value(0x84ABB14) or global_value(0x84ABB08)
    return {
        "netobj": net,
        "ui_state": global_value(0x84ABA50),
        "previous_ui_state": global_value(0x84ABA54),
        "account_error": global_value(0x84ABA5C),
        "account_state": global_value(0x84ABA60),
        "state_name": state_raw.split(b"\0", 1)[0].decode("ascii", "replace") if state_raw else None,
        "error_flag": global_value(0x849BA3D, 1),
        "lsg_obj_a": global_value(0x84ABA70),
        "lsg_obj_b": global_value(0x84ABA74),
        "conn_4f4": read(net + 0x4F4) if net else None,
        "ready_4f8": read(net + 0x4F8) if net else None,
        "auth_candidate": auth_obj,
        "ticket_magic_global": global_value(0xD59F08),
        "auth_fields": {hex(off): read(auth_obj + off) for off in
                        (0, 0x14, 0x18, 0x20, 0xD8, 0x156C)} if auth_obj else None,
    }

k32 = probe.k32
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                 wt.DWORD, ctypes.POINTER(wt.DWORD)]
k32.VirtualProtectEx.restype = wt.BOOL
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.restype = wt.BOOL


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--wait", type=float, default=14.0)
    parser.add_argument("--observe", type=float, default=35.0)
    parser.add_argument("--rva", type=lambda v: int(v, 0), default=PATCH_RVA)
    parser.add_argument("--game-args", default="-q")
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
    command = f'"{exe}" {args.game_args}'
    si = probe.STARTUPINFOW(); si.cb = ctypes.sizeof(probe.STARTUPINFOW)
    pi = probe.PROCESS_INFORMATION()
    if not probe.k32.CreateProcessW(str(exe), ctypes.create_unicode_buffer(command), None, None, False,
                                    probe.CREATE_SUSPENDED | probe.CREATE_UNICODE_ENVIRONMENT, None, str(root),
                                    ctypes.byref(si), ctypes.byref(pi)):
        print("CreateProcessW failed", ctypes.get_last_error(), file=sys.stderr)
        return 2
    pid = pi.dwProcessId
    record = {"build": BUILD, "pid": pid, "command_line": command, "patch": {},
              "events": [], "notes": ["runtime-only patch; on-disk client unchanged"]}
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
        va = base + args.rva
        process = probe.k32.OpenProcess(
            probe.PROCESS_VM_READ | probe.PROCESS_QUERY_INFORMATION | 0x0020 | 0x0008,  # VM_WRITE|VM_OPERATION
            False, pid)
        if not process:
            record["error"] = f"OpenProcess failed {ctypes.get_last_error()}"
            return 3
        original = probe.read_memory(process, va, 2)
        record["patch"] = {"module_base": hex(base), "rva": hex(args.rva), "va": hex(va),
                           "original": original.hex() if original else None,
                           "expected": PATCH_ORIGINAL.hex(),
                           "replacement": PATCH_REPLACEMENT.hex()}
        if original != PATCH_ORIGINAL:
            record["patch"]["verified"] = False
            record["error"] = "original bytes mismatch"
            return 3
        old_protect = wt.DWORD(0)
        if not k32.VirtualProtectEx(process, ctypes.c_void_p(va), 2, PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)):
            record["error"] = f"VirtualProtectEx failed {ctypes.get_last_error()}"
            return 3
        written = ctypes.c_size_t(0)
        ok = k32.WriteProcessMemory(process, ctypes.c_void_p(va), PATCH_REPLACEMENT, 2, ctypes.byref(written))
        k32.VirtualProtectEx(process, ctypes.c_void_p(va), 2, old_protect.value, ctypes.byref(old_protect))
        record["patch"]["written"] = bool(ok) and written.value == 2
        record["patch"]["verified_after"] = (probe.read_memory(process, va, 2) == PATCH_REPLACEMENT)
        # Retain the exact unpacked code used by this run for offline disassembly.
        for code_va, code_size in ((0x7F2000, 0x2000), (0x803000, 0x1000),
                                   (0xB98000, 0x3000), (0xBA9000, 0x2000),
                                   (0xB76000, 0x5000)):
            code = probe.read_memory(process, base + code_va - 0x400000, code_size)
            if code:
                evidence.with_name(f"code-{code_va:x}.bin").write_bytes(code)
        record["events"].append({"event": "patched", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        deadline = time.time() + args.observe
        try:
            while time.time() < deadline:
                time.sleep(1.0)
                alive, exit_code = launcher.process_alive(pid)
                rows = [row for row in launcher.tcp_rows() if row["pid"] == pid]
                windows = launcher.windows_of({pid})
                if alive:
                    net_raw = probe.read_memory(process, base + 0x8269774 - 0x400000, 4)
                    if net_raw and int.from_bytes(net_raw, "little"):
                        net_dump = probe.read_memory(process, int.from_bytes(net_raw, "little"), 0x600)
                        if net_dump:
                            evidence.with_name("netobj-latest.bin").write_bytes(net_dump)
                record["events"].append({"event": "sample", "alive": alive, "exit_code": exit_code,
                                         "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                         "lobby": sample_lobby(process, base) if alive else None,
                                         "tcp": rows, "windows": windows})
                evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
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


