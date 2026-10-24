#!/usr/bin/env python3
"""Run one complete CODOL 1649370 match against server1649370, end to end.

This wraps the manual sequence (lobby, game server, client launch, login,
ring drain, refresh hook, ring forward, connect, sampling, screenshot) into a
single reproducible command and writes a JSON summary.

Usage:
    python tools/run_match.py --name demo --seconds 70 --match-duration 45

Outputs:
    runs/<name>-summary.json     machine-readable result
    runs/<name>-gs.jsonl         game server log
    runs/<name>-screenshot.png   final frame (if a screenshot was captured)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
RUNTIME = Path(r"E:\GAME\COD\1649370\workspaces\offline-runs\20261023-codex-delay-a2\runtime")
CLIENT = "codol1649370-offline.exe"


def log(message: str) -> None:
    print(f"[run_match] {message}", flush=True)


def kill_stale() -> None:
    subprocess.run(["taskkill", "/F", "/IM", CLIENT], capture_output=True)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'server319.lsg|server1649370.gameserver|ring_bridge_1649370' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=30).stdout
        for token in out.split():
            if token.isdigit():
                subprocess.run(["taskkill", "/F", "/PID", token], capture_output=True)
    except Exception:
        pass
    time.sleep(2)


def start(args: list[str], out_path: Path, err_path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-B", "-X", "utf8", *args],
        cwd=str(ROOT),
        stdout=open(out_path, "wb"),
        stderr=open(err_path, "wb"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def wait_for(path: Path, needle: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if needle in path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def run_tool(args: list[str], timeout: float = 180) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def read_state() -> dict:
    code = r"""
import ctypes as C, ctypes.wintypes as W, struct, subprocess
k32=C.WinDLL('kernel32',use_last_error=True)
k32.OpenProcess.restype=W.HANDLE
k32.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]
k32.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
pid=0
out=subprocess.run(['tasklist','/FI','IMAGENAME eq codol1649370-offline.exe','/FO','CSV'],capture_output=True,text=True).stdout
for line in out.splitlines():
    p=[x.strip('"') for x in line.split('","')]
    if len(p)>1 and p[1].isdigit(): pid=int(p[1])
if not pid:
    print('{}'); raise SystemExit
h=k32.OpenProcess(0x1F0FFF,False,pid)
def u32(a):
    b=C.create_string_buffer(4); g=C.c_size_t()
    if not k32.ReadProcessMemory(h,C.c_void_p(a),b,4,C.byref(g)): return None
    return struct.unpack('<I',b.raw)[0]
print(__import__('json').dumps({'pid':pid,'state':u32(0x76446B0),'ui':u32(0x84ABA50)}))
"""
    proc = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", code],
                          capture_output=True, text=True, timeout=60)
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}




BUNDLED_PYTHON = Path(r"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe")


def analyse_frame(tga: Path, png: Path) -> dict:
    """Return frame statistics, using the bundled interpreter when PIL is absent."""
    script = (
        "import sys, json\n"
        "from PIL import Image\n"
        "im = Image.open(sys.argv[1]); im.save(sys.argv[2])\n"
        "small = im.resize((96, 54)).convert('RGB'); px = list(small.getdata())\n"
        "print(json.dumps({'unique_colors': len(set(px)),"
        " 'mean': [sum(c[i] for c in px)//len(px) for i in range(3)],"
        " 'max': max(max(c) for c in px)}))\n"
    )
    for interpreter in (sys.executable, str(BUNDLED_PYTHON)):
        try:
            proc = subprocess.run([interpreter, "-B", "-X", "utf8", "-c", script,
                                   str(tga), str(png)],
                                  capture_output=True, text=True, timeout=120)
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("{"):
                    data = json.loads(line)
                    data["file"] = str(tga)
                    return data
        except Exception:
            continue
    return {"file": str(tga), "error": "no PIL available in any interpreter"}




def capture(name: str, when: int, summary: dict) -> None:
    """Capture one frame at a given time and record its statistics."""
    run_tool(["tools/cbuf_command.py", "--command", "screenshot",
              "--output", f"runs/{name}-cbuf-{when}.json"], timeout=90)
    time.sleep(2)
    shots = sorted((RUNTIME / "main" / "screenshots").glob("*.tga"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not shots:
        return
    tga = RUNS / f"{name}-t{when}.tga"
    shutil.copyfile(shots[0], tga)
    stats = analyse_frame(tga, RUNS / f"{name}-t{when}.png")
    stats["t"] = when
    summary.setdefault("frames", []).append(stats)
    log(f"  frame t={when}: {stats}")



def verify_delivery(name: str) -> dict:
    """Assert the run actually delivered a snapshot to the client.

    Two recent sessions were wasted by interpreting states from runs where
    nothing reached the parser, so this is checked on every run.
    """
    forward = RUNS / f"{name}-forward.json"
    gs_log = RUNS / f"{name}-gs.jsonl"
    snapshots = 0
    if gs_log.exists():
        for line in gs_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"message": "snapshot"' in line:
                snapshots += 1
    return {
        "forward_summary": forward.exists(),
        "snapshots_queued": snapshots,
        "ok": forward.exists() and snapshots > 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="run one end-to-end CODOL 1649370 match")
    parser.add_argument("--name", default="match")
    parser.add_argument("--seconds", type=int, default=70, help="bridge forwarding window")
    parser.add_argument("--match-duration", type=int, default=45,
                        help="seconds until the server sends the end-of-match disconnect")
    parser.add_argument("--snapshot", default="runs/snapshot-hybrid-empty-actors.bin")
    parser.add_argument("--snapshot-delay", type=float, default=20.0)
    parser.add_argument("--snapshot-seq", type=int, default=1000,
                        help="first snapshot sequence; 1000 was accepted after gamestate 3")
    parser.add_argument("--map", default="", help="override the gamestate map name")
    parser.add_argument("--runtime", default="20261023-codex-delay-a2")
    parser.add_argument("--lsg-port", type=int, default=28969)
    parser.add_argument("--gs-port", type=int, default=28971)
    parser.add_argument("--bind-port", type=int, default=29000)
    parser.add_argument("--screenshot-at", default="",
                        help="comma separated seconds at which to capture a frame")
    parser.add_argument("--stage-loose", action="store_true",
                        help="copy the five verified same-build loose packs into this runtime")
    parser.add_argument("--skip-clean", action="store_true",
                        help="leave unrelated project servers running")
    args = parser.parse_args()

    RUNS.mkdir(exist_ok=True)
    name = args.name
    shoot_at = {int(x) for x in args.screenshot_at.split(",") if x.strip().isdigit()}
    summary: dict = {"name": name, "steps": {}}

    if not args.skip_clean:
        log("cleaning stale processes")
        kill_stale()

    log("starting lobby/auth")
    start(["-m", "server319.lsg",
           "--cert", "runs/20261020-live-derived01/tls/auth.crt",
           "--key", "runs/20261020-live-derived01/tls/auth.key",
           "--port", str(args.lsg_port), "--log", f"runs/{name}-lsg.jsonl",
           "--seconds", "3600", "--allow-auth-tls"],
          RUNS / f"{name}-lsg.out", RUNS / f"{name}-lsg.err")
    time.sleep(2)

    log("starting game server")
    gs_args = ["-m", "server1649370.gameserver",
               "--port", str(args.gs_port), "--log", f"runs/{name}-gs.jsonl",
               "--delay-send", "10", "--gamestate-source", "native",
               "--snapshot-file", args.snapshot, "--snapshot-delay", str(args.snapshot_delay),
               "--snapshot-seq", str(args.snapshot_seq), "--snapshot-repeat", "120",
               "--snapshot-interval", "1.5",
               "--oob-command", "disconnect",
               "--match-duration", str(args.match_duration)]
    if args.map:
        gs_args += ["--gamestate-map", args.map]
    start(gs_args, RUNS / f"{name}-gs.out", RUNS / f"{name}-gs.err")
    time.sleep(2)

    log("launching client")
    start(["tools/launch_1649370.py", "--full", "--seconds", "400",
           "--local-profile", "--loopback-tcp-guard", "--local-auth-lsg",
           "--reuse-runtime", args.runtime, "--name", name, "--trace-files"],
          RUNS / f"{name}-launch.out", RUNS / f"{name}-launch.err")
    ready = wait_for(RUNS / f"{name}-launch.out", "engine-init", 40)
    summary["steps"]["engine_init"] = ready
    if not ready:
        log("engine never initialised")
        (RUNS / f"{name}-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 1
    log("engine ready")

    if args.stage_loose:
        runtime = Path(r"E:\GAME\COD\1649370\workspaces\offline-runs") / args.runtime / "runtime"
        destination = runtime / "devraw_shared"
        staged = 0
        for pack in ("crash-tropical", "crossfire", "gametype", "dmz", "survival"):
            source = RUNS / f"20261022-{pack}-loose-v461" / "main"
            if not source.is_dir():
                raise FileNotFoundError(source)
            for item in source.rglob("*"):
                if not item.is_file():
                    continue
                target = destination / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != item.stat().st_size:
                    shutil.copy2(item, target)
                    staged += 1
        summary["steps"]["loose_staged"] = staged
        log(f"staged {staged} loose files")

    log("driving login state machine")
    code, out = run_tool(["tools/drive_login_state_machine.py", "--set-ui-state", "1",
                          "--ticks", "40", "--interval", "0.4",
                          "--output", f"runs/{name}-login.json"])
    summary["steps"]["login"] = code == 0
    time.sleep(18)

    log("blocking ring-a")
    code, _ = run_tool(["tools/ring_bridge_1649370.py", "--output", f"runs/{name}-drain.json",
                        "ring-a-drain", "block"])
    summary["steps"]["ring_a_blocked"] = code == 0

    log("installing refresh hook")
    code, _ = run_tool(["tools/install_refresh_hook.py", "--install"])
    summary["steps"]["refresh_hook"] = code == 0

    log("starting ring bridge")
    start(["tools/ring_bridge_1649370.py", "--output", f"runs/{name}-forward.json",
           "forward", "--target", f"127.0.0.1:{args.gs_port}",
           "--seconds", str(args.seconds), "--adr-type", "2", "--fake-stats",
           "--keepalive", "--bind-port", str(args.bind_port),
           "--reliable-until-state", "0", "--max-events", "1200"],
          RUNS / f"{name}-fwd.out", RUNS / f"{name}-fwd.err")
    time.sleep(1)

    log("connecting")
    code, out = run_tool(["tools/ring_bridge_1649370.py", "--output", f"runs/{name}-connect.json",
                          "connect", "--address", f"127.0.0.1:{args.bind_port}", "--settle", "2"])
    summary["steps"]["connect"] = code == 0

    samples = []
    started = time.time()
    targets = [20, 35, 50, 65]
    for target in targets:
        delay = target - (time.time() - started)
        if delay > 0:
            time.sleep(delay)
        info = read_state()
        info["t"] = target
        samples.append(info)
        log(f"t={target}s state={info.get('state')} ui={info.get('ui')}")
        if target in shoot_at:
            capture(name, target, summary)
    summary["samples"] = samples

    log("capturing screenshot")
    run_tool(["tools/cbuf_command.py", "--command", "screenshot",
              "--output", f"runs/{name}-cbuf.json"], timeout=90)
    time.sleep(3)
    shots = sorted((RUNTIME / "main" / "screenshots").glob("*.tga"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if shots:
        target = RUNS / f"{name}-screenshot.tga"
        shutil.copyfile(shots[0], target)
        summary["frame"] = analyse_frame(target, RUNS / f"{name}-screenshot.png")

    summary["delivery"] = verify_delivery(name)
    (RUNS / f"{name}-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"summary written to runs/{name}-summary.json")
    log(f"states: {[s.get('state') for s in samples]}")
    log(f"delivery: {summary['delivery']}")
    if not summary["delivery"]["ok"]:
        log("WARNING: this run did not deliver as expected - do not interpret"
            " traces or states from it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
