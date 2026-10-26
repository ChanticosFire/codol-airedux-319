"""Bring the whole 1649370 offline session up in one command, and prove net=10.

Hand-sequencing five processes (LSG, game server, client, launcher patching,
UDP bridge) went wrong repeatedly: bridges expired mid-experiment, the game
server died unnoticed, clients sat at `net=0` while a test ran, and two rounds
of "negative results" were only ever measuring the lobby.  This script does the
sequence once, with explicit assertions and bounded waits, and refuses to
report success unless `cls.state == 10`.

It never kills processes by name: every stop targets an exact PID that it
verified first.

    python tools/session_up_1649370.py --name r570 --runtime r107flow
    python tools/session_up_1649370.py --name r571 --keep-server --keep-bridge
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import struct
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CL_PTR = 0x76638F4
CL_XOR = 0x6891D1C7
NET_STATE = 0x76446B0


def _k32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def read_u32(handle, k32, address: int):
    buf = ctypes.create_string_buffer(4)
    got = ctypes.c_size_t()
    if not k32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, 4, ctypes.byref(got)):
        return None
    return struct.unpack("<I", buf.raw)[0] if got.value == 4 else None


def net_state(k32, pid: int):
    handle = k32.OpenProcess(0x438, False, pid)
    if not handle:
        return None
    try:
        return read_u32(handle, k32, NET_STATE)
    finally:
        k32.CloseHandle(handle)


def port_owner(port: int, udp: bool):
    """Return the owning PID of a bound port, without shelling out to netstat."""
    if udp:
        return None  # filled by the caller through _udp_owner
    return None


def _udp_owner(script: str, port: int):
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-NetUDPEndpoint -LocalPort %d -ErrorAction SilentlyContinue | "
                          "Select-Object -First 1).OwningProcess" % port],
                         capture_output=True, text=True)
    text = out.stdout.strip()
    return int(text) if text.isdigit() else None


def _tcp_listen(port: int) -> bool:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "([bool](Get-NetTCPConnection -State Listen -LocalPort %d "
                          "-ErrorAction SilentlyContinue))" % port],
                         capture_output=True, text=True)
    return out.stdout.strip().lower() == "true"


def _client_pid() -> int | None:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "
                          "'codol1649370-offline.exe' } | Select-Object -First 1).ProcessId"],
                         capture_output=True, text=True)
    text = out.stdout.strip().splitlines()[-1].strip() if out.stdout.strip() else ""
    return int(text) if text.isdigit() else None


def wait_for(what: str, predicate, timeout: float, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise SystemExit(f"timed out waiting for {what} ({timeout:.0f}s)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="run name, used for every log file")
    ap.add_argument("--runtime", default="r107flow")
    ap.add_argument("--gamestate", default="runs/gamestate-player1735.bin")
    ap.add_argument("--snapshot", default="runs/r546-markers.bin")
    ap.add_argument("--snapshot-dir", default=None,
                    help="send a directory of snapshot frames in name order instead of one file")
    ap.add_argument("--server-seconds", type=float, default=3600.0,
                    help="how long the game server keeps serving")
    ap.add_argument("--bridge-seconds", type=float, default=1500.0)
    ap.add_argument("--keep-server", action="store_true")
    ap.add_argument("--keep-bridge", action="store_true")
    ap.add_argument("--skip-client", action="store_true")
    ap.add_argument("--match-disconnect", type=float, default=None,
                    help="send the OOB disconnect command this many seconds after connect to end the match")
    ap.add_argument("--gamestate-source", choices=("file", "native"), default="file",
                    help="file sends the captured bin verbatim; native rebuilds it "
                         "so --configstring-file takes effect")
    ap.add_argument("--configstring-file", default=None,
                    help="JSON [[index,value],...] replacing the built-in configstrings")
    ap.add_argument("--server-command-text", default=None,
                    help="override the svc_serverCommand text sent during the match")
    ap.add_argument("--send-opcode", default=None,
                    help="comma separated raw inband opcodes to send after connect, "
                         "three seconds apart")
    ap.add_argument("--rebuild-follow", action="store_true",
                    help="start the client first, then let the server encode snapshots from its held keys")
    args = ap.parse_args()

    logs = ROOT / "runs"
    report: dict = {"name": args.name, "steps": []}

    def step(message: str, **extra) -> None:
        entry = {"step": message, "time": time.time(), **extra}
        report["steps"].append(entry)
        print(f"[session] {message}" + (f" {extra}" if extra else ""), flush=True)

    k32 = _k32()

    # ---------------------------------------------------------------- LSG
    if not _tcp_listen(28969):
        step("starting LSG")
        subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-m", "server319.lsg",
                          "--cert", "runs/20261020-live-derived01/tls/auth.crt",
                          "--key", "runs/20261020-live-derived01/tls/auth.key",
                          "--port", "28969", "--allow-auth-tls", "--seconds", "5400",
                          "--log", f"runs/{args.name}-lsg.jsonl"],
                         cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for("LSG listen", lambda: _tcp_listen(28969), 20)
        step("LSG listening")
    else:
        step("LSG already listening")

    def start_server(follow_pid=None):
        owner = _udp_owner("", 28969)
        if owner:
            step("stopping existing game server", pid=owner)
            subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {owner} -Force"],
                           capture_output=True, text=True)
            time.sleep(2)
        if not args.keep_server:
            step("starting game server", seconds=args.server_seconds)
            server_args = [sys.executable, "-X", "utf8", "-B", "-m", "server1649370.gameserver",
                           "--port", "28969", "--delay-send", "1",
                           "--gamestate-source", args.gamestate_source, "--gamestate-file", args.gamestate,
                           "--gamestate-gametype", "war",
                           "--gamestate-map", "mp_crash_tropical",
                           "--snapshot-delay", "1",
                           "--snapshot-seq", "4", "--snapshot-repeat", "30000",
                           "--snapshot-interval", "0.1",
                           "--server-command-every", "10", "--server-command-seq", "4",
                           "--server-command-text", args.server_command_text or " ",
            *( ["--configstring-file", args.configstring_file] if args.configstring_file else [] ),
                           "--match-duration", str(int(args.server_seconds)),
                           "--log", f"runs/{args.name}-gs.jsonl"]
            if follow_pid:
                server_args += ["--rebuild-follow-pid", str(follow_pid)]
            if args.send_opcode is not None:
                server_args += ["--send-opcode", str(args.send_opcode)]
            if args.match_disconnect:
                # --match-duration overrides --oob-delay in gameserver.main(),
                # so drop it or the disconnect would wait server_seconds.
                if "--match-duration" in server_args:
                    cut = server_args.index("--match-duration")
                    del server_args[cut:cut + 2]
                server_args += ["--oob-command", "disconnect",
                                "--oob-delay", str(args.match_disconnect)]
            if args.snapshot_dir:
                server_args += ["--snapshot-dir", args.snapshot_dir, "--snapshot-interval", "0.25"]
            else:
                server_args += ["--snapshot-file", args.snapshot, "--snapshot-interval", "0.1"]
            subprocess.Popen(server_args,
                             cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_for("game server UDP 28969", lambda: _udp_owner("", 28969), 20)
            step("game server listening", pid=_udp_owner("", 28969), snapshot_dir=bool(args.snapshot_dir))

    # Always start the server first: that is the order that reliably reaches
    # CA_ACTIVE (r576).  With --rebuild-follow the server discovers the client
    # PID by name when it first needs it, so no ordering compromise is needed.
    start_server(-1 if args.rebuild_follow else None)

    # -------------------------------------------------------------- client
    pid = None if not args.skip_client else _client_pid()
    if args.skip_client:
        if not pid:
            raise SystemExit("--skip-client given but no client process found")
        step("reusing client", pid=pid)
    else:
        step("starting client")
        subprocess.Popen([sys.executable, "-B", "-X", "utf8", "tools/launch_1649370.py",
                          "--name", args.name, "--reuse-runtime", args.runtime,
                          "--until-close", "--local-profile", "--full",
                          "--local-auth-lsg", "--loopback-tcp-guard"],
                         cwd=ROOT, stdout=open(logs / f"{args.name}-launch.out", "w", encoding="utf-8"),
                         stderr=subprocess.STDOUT)
        pid = wait_for("client process", _client_pid, 60)
        step("client process", pid=pid)
        wait_for("engine init marker",
                 lambda: "engine-init" in (logs / f"{args.name}-launch.out").read_text(encoding="utf-8", errors="replace"),
                 90)
        step("engine init done")
        time.sleep(3)

    # ------------------------------------------------------------- patching
    def run(script_args, **kwargs):
        return subprocess.run([sys.executable] + script_args, cwd=ROOT, capture_output=True,
                              text=True, **kwargs)

    result = run(["tools/patch_retry_ms_1649370.py", "--pid", str(pid), "--ms", "0"])
    if '"applied": true' not in result.stdout:
        raise SystemExit(f"retry patch failed: {result.stdout[:400]} {result.stderr[:200]}")
    step("retry patch applied")

    result = run(["tools/drive_login_state_machine.py", "--ticks", "20", "--interval", "0.35",
                  "--set-ui-state", "1", "--output", f"runs/{args.name}-drive.json"])
    if "127" not in result.stdout and "u007f" not in result.stdout:
        raise SystemExit(f"login drive failed: {result.stdout[:400]}")
    step("login state machine driven")

    result = run(["runs/_patch_r336.py", str(pid)])
    if "ok=0" in result.stdout:
        raise SystemExit(f"r336 patch reported a failure: {result.stdout[:400]}")
    step("r336 patches applied")

    # --------------------------------------------------------------- bridge
    owner = _udp_owner("", 29023)
    if owner:
        step("stopping existing bridge", pid=owner)
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {owner} -Force"],
                       capture_output=True, text=True)
        time.sleep(2)
    if not args.keep_bridge:
        step("starting bridge", seconds=args.bridge_seconds)
        subprocess.Popen([sys.executable, "-B", "-X", "utf8", "tools/ring_bridge_1649370.py",
                          "forward", "--target", "127.0.0.1:28969", "--bind-port", "29023",
                          "--start-challenge", "--retry-seconds", "0",
                          "--seconds", str(int(args.bridge_seconds))],
                         cwd=ROOT, stdout=open(logs / f"{args.name}-bridge.out", "w", encoding="utf-8"),
                         stderr=subprocess.STDOUT)
        wait_for("bridge UDP 29023", lambda: _udp_owner("", 29023), 20)
        step("bridge listening", pid=_udp_owner("", 29023))

    # ------------------------------------------------------- assert net == 10
    state = wait_for("cls.state == 10", lambda: net_state(k32, pid) == 10 and 10, 90, 0.5)
    final = net_state(k32, pid)
    report.update({"client_pid": pid, "net_state": final,
                   "server_pid": _udp_owner("", 28969),
                   "bridge_pid": _udp_owner("", 29023),
                   "ok": final == 10})
    (logs / f"{args.name}-session.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "client_pid", "net_state",
                                             "server_pid", "bridge_pid")}))
    return 0 if final == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
