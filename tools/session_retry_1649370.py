"""Run session_up_1649370.py with bounded retries and clean recovery.

Connection establishment currently fails about 40% of the time (measured
r717-r721): the client exits while still at net_state 3-4, session_up times out
and no session record is written.  Each attempt is independent, so wrapping the
sequence in a few retries with an exact-PID cleanup between them turns a 60%
success rate into ~94% over three attempts without changing any game logic.

    python tools/session_retry_1649370.py --name r722 --attempts 3 -- \
        --runtime r107flow --gamestate runs/r694-gamestate-start.bin \
        --snapshot runs/r696-weapon78-health100.bin --server-seconds 300 \
        --bridge-seconds 300 --restore-weapon-handler \
        --restore-weapon-lookup-branch --restore-weapon-init-indexing \
        --weapon-lookup-fallback --server-command-text off
"""
from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UDP_PORTS = (28969, 29023)


def _udp_owner(port: int) -> int | None:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-NetUDPEndpoint -LocalPort %d -ErrorAction SilentlyContinue | "
         "Select-Object -First 1).OwningProcess" % port],
        capture_output=True, text=True)
    text = out.stdout.strip()
    return int(text) if text.isdigit() else None


def _tcp_owner(port: int) -> int | None:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-NetTCPConnection -State Listen -LocalPort %d -ErrorAction SilentlyContinue | "
         "Select-Object -First 1).OwningProcess" % port],
        capture_output=True, text=True)
    text = out.stdout.strip()
    return int(text) if text.isdigit() else None


def _client_pids() -> list[int]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "
         "'codol1649370-offline.exe' } | Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True)
    return [int(line) for line in out.stdout.split() if line.strip().isdigit()]


def cleanup() -> dict:
    k32 = ctypes.WinDLL("kernel32", last_error=True) if False else ctypes.WinDLL("kernel32")
    killed = []
    pids = set(_client_pids())
    for port in UDP_PORTS:
        owner = _udp_owner(port)
        if owner:
            pids.add(owner)
    lsg = _tcp_owner(28969)
    if lsg:
        pids.add(lsg)
    for pid in sorted(pids):
        out = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                             capture_output=True, text=True)
        killed.append({"pid": pid, "ok": out.returncode == 0})
    time.sleep(2)
    return {"killed": killed}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--settle", type=float, default=3.0)
    ap.add_argument("--after-success", default=None,
                    help="command to run right after a successful attempt; "
                         "{name} and {pid} are substituted")
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    extra = [item for item in args.rest if item != "--"]

    attempts = []
    for attempt in range(1, args.attempts + 1):
        name = args.name if attempt == 1 else f"{args.name}-a{attempt}"
        command = [sys.executable, "tools/session_up_1649370.py", "--name", name, *extra]
        print(f"[retry] attempt {attempt}/{args.attempts}: {' '.join(command[:4])}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        attempts.append({"attempt": attempt, "name": name, "returncode": result.returncode})
        if result.returncode == 0:
            print(f"[retry] success on attempt {attempt} (name={name})", flush=True)
            if args.after_success:
                import json
                session_file = ROOT / "runs" / f"{name}-session.json"
                pid = 0
                if session_file.is_file():
                    try:
                        pid = int(json.loads(session_file.read_text(encoding="utf-8"))
                                  .get("client_pid") or 0)
                    except (ValueError, KeyError):
                        pid = 0
                hook = args.after_success.replace("{name}", name).replace("{pid}", str(pid))
                print(f"[retry] after-success (pid={pid}): {hook}", flush=True)
                subprocess.run(hook, cwd=ROOT, shell=True)
            print(f"[retry] summary {attempts}", flush=True)
            return 0
        print(f"[retry] attempt {attempt} failed, cleaning up", flush=True)
        print(f"[retry] cleanup {cleanup()}", flush=True)
        time.sleep(args.settle)
    print(f"[retry] all {args.attempts} attempts failed: {attempts}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
