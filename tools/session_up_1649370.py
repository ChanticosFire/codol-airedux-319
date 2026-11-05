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
    ap.add_argument("--gametype", default="war",
                    help="gametype in the game server's connect response")
    ap.add_argument("--snapshot", default="runs/r546-markers.bin")
    ap.add_argument("--snapshot-dir", default=None,
                    help="send a directory of snapshot frames in name order instead of one file")
    ap.add_argument("--server-seconds", type=float, default=3600.0,
                    help="how long the game server keeps serving")
    ap.add_argument("--bridge-seconds", type=float, default=1500.0)
    ap.add_argument("--ring-a-length-mode", choices=("slot", "nul"), default="slot",
                    help="outgoing ring A binary length mode; nul is the legacy A/B control")
    ap.add_argument("--preserve-binary-stats", action="store_true",
                    help="opt in to forwarding the native binary stats OOB payload")
    ap.add_argument("--inspect-stats-upload", action="store_true",
                    help="ask the game server to validate uploaded stats in memory without changing replies")
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
    ap.add_argument("--server-command-transport", choices=("separate", "inline"),
                    default="separate", help="opt in to ACK-resend server commands inside snapshots")
    ap.add_argument("--server-command-every", type=int, default=200,
                    help="snapshot interval between newly queued server commands")
    ap.add_argument("--max-unacked-snapshots", type=int, default=0,
                    help="opt in to ACK-paced snapshot delivery; requires --decode-client-input")
    ap.add_argument("--scoreboard-reply", action="store_true",
                    help="reply to the client's s poll using current single-player match scores")
    ap.add_argument("--decode-client-input", action="store_true",
                    help="read-only usercmd decoding using the selected gamestate's checksum feed; requires server-command-text off")
    ap.add_argument("--input-motion-probe", action="store_true",
                    help="opt-in bounded r738 four-axis origin feedback; no synthetic ammo changes")
    ap.add_argument("--input-fire-event-probe", action="store_true",
                    help="opt-in attack-edge event ID 54 with unchanged clip; requires input motion probe")
    ap.add_argument("--send-opcode", default=None,
                    help="comma separated raw inband opcodes to send after connect, "
                         "three seconds apart")
    ap.add_argument("--rebuild-follow", action="store_true",
                    help="start the client first, then let the server encode snapshots from its held keys")
    ap.add_argument("--restore-weapon-handler", action="store_true",
                    help="after r336 compatibility patches, restore the original 0x59B560 weapon handler for a controlled probe")
    ap.add_argument("--trace-weapon-registration", action="store_true",
                    help="with --restore-weapon-handler, record each weapon slot and resolved ID before validation")
    ap.add_argument("--trace-weapon-lookup", action="store_true",
                    help="with --restore-weapon-handler, also trace 0x42F2F0 lookup returns")
    ap.add_argument("--trace-weapon-compare105", action="store_true",
                    help="with --restore-weapon-handler, trace candidate comparisons at table count 105")
    ap.add_argument("--trace-weapon-scan", action="store_true",
                    help="with --restore-weapon-handler, trace lookup scan entry and loop")
    ap.add_argument("--weapon-lookup-fallback", action="store_true",
                    help="with --restore-weapon-handler, try exact-name lookup before the original function")
    ap.add_argument("--tolerate-weapon-id-mismatch", action="store_true",
                    help="with --restore-weapon-handler, bypass only its ID equality error branch for a controlled probe")
    ap.add_argument("--restore-weapon-lookup-branch", action="store_true",
                    help="restore the original conditional 0x42F32C branch after r336 for an isolated A/B probe")
    ap.add_argument("--restore-weapon-init-indexing", action="store_true",
                    help="restore original per-ID table access at 0x58F3B9 after r336")
    ap.add_argument("--restore-weapon-cache-indexing", action="store_true",
                    help="restore original per-ID table access at 0x58EF76 after r336 "
                         "(inside the 0x58EF60 model-cache fill)")
    ap.add_argument("--cbuf-command", default=None,
                    help="inject one native cbuf command (for example a cvar set) "
                         "through the launcher, before the client connects")
    args = ap.parse_args()
    input_checksum_feed = None
    if args.decode_client_input:
        if args.gamestate_source != "file" or (args.server_command_text != "off" and
                                                args.server_command_transport != "inline"):
            ap.error("--decode-client-input requires a file gamestate and inline or disabled server commands")
        from build_gamestate_1649370 import decode as decode_gamestate
        input_checksum_feed = decode_gamestate((ROOT / args.gamestate).read_bytes()).checksum_feed
    if args.input_motion_probe and not args.decode_client_input:
        ap.error("--input-motion-probe requires --decode-client-input")
    if args.input_motion_probe and args.snapshot_dir:
        ap.error("--input-motion-probe requires a single r738 snapshot file")
    if args.input_fire_event_probe and not args.input_motion_probe:
        ap.error("--input-fire-event-probe requires --input-motion-probe")
    if args.trace_weapon_registration and not args.restore_weapon_handler:
        ap.error("--trace-weapon-registration requires --restore-weapon-handler")
    if args.trace_weapon_lookup and not args.restore_weapon_handler:
        ap.error("--trace-weapon-lookup requires --restore-weapon-handler")
    if args.trace_weapon_compare105 and not args.restore_weapon_handler:
        ap.error("--trace-weapon-compare105 requires --restore-weapon-handler")
    if args.trace_weapon_scan and not args.restore_weapon_handler:
        ap.error("--trace-weapon-scan requires --restore-weapon-handler")
    if args.weapon_lookup_fallback and not args.restore_weapon_handler:
        ap.error("--weapon-lookup-fallback requires --restore-weapon-handler")
    if args.tolerate_weapon_id_mismatch and not args.restore_weapon_handler:
        ap.error("--tolerate-weapon-id-mismatch requires --restore-weapon-handler")

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
                           *( ["--checksum-feed", str(input_checksum_feed), "--decode-client-input"]
                              if args.decode_client_input else [] ),
                           *( ["--input-motion-probe"] if args.input_motion_probe else [] ),
                           *( ["--input-fire-event-probe"] if args.input_fire_event_probe else [] ),
                           *( ["--inspect-stats-upload"] if args.inspect_stats_upload else [] ),
                           "--gamestate-gametype", args.gametype,
                           "--gamestate-map", "mp_crash_tropical",
                           "--snapshot-delay", "1",
                           "--snapshot-seq", "4", "--snapshot-repeat", "30000",
                           "--snapshot-interval", "0.1",
            *( ["--server-command-every", str(args.server_command_every),
                "--server-command-seq", "0" if args.server_command_transport == "inline" else "4",
                "--server-command-text", args.server_command_text or " ",
                "--server-command-transport", args.server_command_transport]
               if args.server_command_text != "off" else [] ),
            *( ["--max-unacked-snapshots", str(args.max_unacked_snapshots)]
               if args.max_unacked_snapshots else [] ),
            *( ["--scoreboard-reply"] if args.scoreboard_reply else [] ),
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
        launch_args = [sys.executable, "-B", "-X", "utf8", "tools/launch_1649370.py",
                       "--name", args.name, "--reuse-runtime", args.runtime,
                       "--until-close", "--local-profile", "--full",
                       "--local-auth-lsg", "--loopback-tcp-guard"]
        if args.cbuf_command:
            launch_args += ["--cbuf-command", args.cbuf_command]
        subprocess.Popen(launch_args,
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
    if args.restore_weapon_lookup_branch:
        result = run(["tools/restore_weapon_lookup_branch_1649370.py", "--pid", str(pid)])
        if result.returncode or '"restored": true' not in result.stdout:
            raise SystemExit(f"weapon lookup branch restore failed: {result.stdout[:400]} {result.stderr[:200]}")
        step("original weapon lookup branch restored")
    if args.restore_weapon_init_indexing:
        result = run(["tools/restore_weapon_table_indexing_1649370.py", "--pid", str(pid),
                      "--site", "init"])
        if result.returncode or '"restored": true' not in result.stdout:
            raise SystemExit(f"weapon init indexing restore failed: {result.stdout[:400]} {result.stderr[:200]}")
        step("original weapon init indexing restored")
    if args.restore_weapon_cache_indexing:
        result = run(["tools/restore_weapon_table_indexing_1649370.py", "--pid", str(pid),
                      "--site", "other"])
        if result.returncode or '"restored": true' not in result.stdout:
            raise SystemExit(f"weapon cache indexing restore failed: {result.stdout[:400]} {result.stderr[:200]}")
        step("original weapon cache indexing restored")
    if args.restore_weapon_handler:
        # r336 replaces this whole registration/validation function with RET.
        # Restore only these ten bytes before the bridge can connect. The
        # remaining transport compatibility patches stay in place.
        result = run(["tools/hook_any_1649370.py", "--pid", str(pid),
                      "--target", "0x59B560", "--restore", "--original-hex",
                      "558bec568db748170000"])
        if '"restored": true' not in result.stdout or '"bytes_after": "558bec568db748170000"' not in result.stdout:
            raise SystemExit(f"weapon handler restore failed: {result.stdout[:400]} {result.stderr[:200]}")
        step("original weapon handler restored")
        if args.weapon_lookup_fallback:
            result = run(["tools/weapon_lookup_fallback_1649370.py", "--pid", str(pid),
                          "--meta", f"runs/{args.name}-weapon-lookup-fallback-meta.json", "--install"])
            if result.returncode or '"installed": true' not in result.stdout:
                raise SystemExit(f"weapon lookup fallback failed: {result.stdout[:400]} {result.stderr[:200]}")
            step("weapon lookup fallback installed")
        if args.tolerate_weapon_id_mismatch:
            result = run(["tools/patch_weapon_assert_1649370.py", "--pid", str(pid)])
            if result.returncode or '"applied": true' not in result.stdout:
                raise SystemExit(f"weapon ID branch patch failed: {result.stdout[:400]} {result.stderr[:200]}")
            step("weapon ID mismatch branch bypassed")
        if args.trace_weapon_registration:
            result = run(["tools/trace_weapon_registration_1649370.py", "--pid", str(pid),
                          "--meta", f"runs/{args.name}-weapon-trace-meta.json", "--install"])
            if result.returncode:
                raise SystemExit(f"weapon trace install failed: {result.stdout[:400]} {result.stderr[:200]}")
            step("weapon registration trace installed")
        if args.trace_weapon_lookup:
            result = run(["tools/trace_weapon_registration_1649370.py", "--pid", str(pid),
                          "--site", "post_lookup", "--meta",
                          f"runs/{args.name}-weapon-lookup-trace-meta.json", "--install"])
            if result.returncode:
                raise SystemExit(f"weapon lookup trace install failed: {result.stdout[:400]} {result.stderr[:200]}")
            step("weapon lookup trace installed")
        if args.trace_weapon_compare105:
            result = run(["tools/trace_weapon_compare105_1649370.py", "--pid", str(pid),
                          "--meta", f"runs/{args.name}-weapon-compare105-meta.json", "--install"])
            if result.returncode:
                raise SystemExit(f"weapon comparison trace install failed: {result.stdout[:400]} {result.stderr[:200]}")
            step("weapon comparison trace installed")
        if args.trace_weapon_scan:
            for site in ("scan_start", "scan_loop"):
                result = run(["tools/trace_weapon_registration_1649370.py", "--pid", str(pid),
                              "--site", site, "--meta", f"runs/{args.name}-{site}-meta.json", "--install"])
                if result.returncode:
                    raise SystemExit(f"weapon {site} trace install failed: {result.stdout[:400]} {result.stderr[:200]}")
            step("weapon lookup scan trace installed")

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
                          "--ring-a-length-mode", args.ring_a_length_mode,
                          *( ["--preserve-binary-stats"] if args.preserve_binary_stats else [] ),
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
