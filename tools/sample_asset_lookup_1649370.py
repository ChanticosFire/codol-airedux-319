"""Sample every asset-name lookup a live 1649370 client performs (read-only).

`0x660B00` is the engine lookup that takes one NUL terminated name on the stack
(`push name; call 0x660B00`).  Asset registration during map load goes through
it, so recording the names it is asked for answers the question the static
tools cannot: did the client ever ask for a first-person model?

The transparent stub in `tools/hook_any_1649370.py` records the call count and
copies the first argument at call time.  This driver installs that stub, polls
the slots until the deadline, and then restores the original prologue.

    python tools/sample_asset_lookup_1649370.py --seconds 120 --out runs/r683-assets.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = 0x660B00
ORIGINAL = "558bec81ec0c010000"
SLOT = 0xE54BD00
SLOT_COUNT = SLOT
SLOT_ARG0 = SLOT + 8
SLOT_ECX = SLOT + 0x10
SLOT_CAPTURE = SLOT + 0x40


def client_pid() -> int | None:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "
         "'codol1649370-offline.exe' } | Select-Object -First 1).ProcessId"],
        capture_output=True, text=True)
    text = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
    return int(text) if text.isdigit() else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--wait", type=float, default=120, help="seconds to wait for a client")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--interval", type=float, default=0.004)
    ap.add_argument("--capture", type=int, default=48)
    ap.add_argument("--target", type=lambda text: int(text, 0), default=DEFAULT_TARGET,
                    help="function entry to hook; 0x660b00 (weapon name lookup) or "
                         "0x661b80 (asset lookup, type in ecx)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    target = args.target
    original_hex = None
    saved = ROOT / "runs" / f"hook-{target:x}-original.bin"
    if saved.is_file():
        original_hex = saved.read_bytes().hex()
    if original_hex is None:
        original_hex = ORIGINAL if target == DEFAULT_TARGET else None

    deadline = time.monotonic() + args.wait
    pid = args.pid
    while not pid and time.monotonic() < deadline:
        pid = client_pid()
        if not pid:
            time.sleep(0.2)
    if not pid:
        raise SystemExit("no client process appeared")
    print(f"[sample] client pid {pid}", flush=True)

    install = subprocess.run(
        [sys.executable, "tools/hook_any_1649370.py", "--pid", str(pid),
         "--target", hex(target), "--len", "9", "--capture", str(args.capture),
         "--capture-src", "arg0"],
        cwd=ROOT, capture_output=True, text=True)
    print(f"[sample] install rc={install.returncode}", flush=True)
    if install.returncode:
        print(install.stdout[-500:], install.stderr[-300:], flush=True)
        raise SystemExit("hook install failed")

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x438, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess failed for {pid}")

    head = ctypes.create_string_buffer(0x14)
    got = ctypes.c_size_t()
    samples: list[dict] = []
    seen: dict[tuple[str, int], dict] = {}
    last_count = -1
    misses = 0
    reads = 0
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(SLOT_COUNT), head, 0x14,
                                     ctypes.byref(got)):
            time.sleep(args.interval)
            continue
        reads += 1
        count, _ret, arg0, _arg1, ecx = struct.unpack("<5I", head.raw[:0x14])
        if count != last_count:
            if last_count >= 0 and count - last_count > 1:
                misses += count - last_count - 1
            last_count = count
            capture = ctypes.create_string_buffer(args.capture)
            if k32.ReadProcessMemory(handle, ctypes.c_void_p(SLOT_CAPTURE), capture,
                                     args.capture, ctypes.byref(got)):
                text = capture.raw[:got.value].split(b"\x00")[0]
                name = text.decode("latin-1", "replace")
                key = (name, ecx)
                entry = seen.get(key)
                if entry is None:
                    seen[key] = {"name": name, "ecx": ecx, "first_count": count, "hits": 1}
                    if len(samples) < 4000:
                        samples.append({"count": count, "name": name,
                                        "arg0": hex(arg0), "ecx": hex(ecx)})
                else:
                    entry["hits"] += 1
        time.sleep(args.interval)

    restore_args = [sys.executable, "tools/hook_any_1649370.py", "--pid", str(pid),
                    "--target", hex(target), "--restore"]
    if original_hex:
        restore_args += ["--original-hex", original_hex]
    restore = subprocess.run(restore_args, cwd=ROOT, capture_output=True, text=True)
    ordered = sorted(seen.values(), key=lambda item: item["first_count"])
    report = {
        "pid": pid,
        "target": hex(target),
        "reads": reads,
        "final_count": last_count,
        "missed_calls": misses,
        "unique_names": len(seen),
        "names": [entry["name"] for entry in ordered][:4000],
        "entries": [{"name": entry["name"], "ecx": hex(entry["ecx"]),
                     "hits": entry["hits"]} for entry in ordered][:4000],
        "restore_rc": restore.returncode,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("pid", "reads", "final_count", "missed_calls",
                       "unique_names", "restore_rc")}, indent=1))
    k32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
