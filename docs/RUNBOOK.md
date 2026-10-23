# server1649370 runbook

Practical operations guide for the CODOL 1649370 self-hosted server.
Everything here is verified in this repository; see `RELEASE.md` for the
capability list and `docs/SNAPSHOT-FORMAT.md` for the protocol notes.

## 1. Prerequisites

| Item | Value |
|---|---|
| Client build | 1649370 (`codol1649370-offline.exe`, image base `0x400000`, 32-bit) |
| Client runtime | `E:\GAME\COD\1649370\workspaces\offline-runs\20261023-codex-delay-a2\runtime` |
| Lobby/auth cert | `runs/20261020-live-derived01/tls/auth.crt` + `auth.key` |
| Python | any 3.11+ for the server tools; the bundled runtime python has Pillow for image stats |
| Baseline snapshot | `runs/snapshot-hybrid-empty-actors.bin` (167 B, the only body that reaches state 10) |

## 2. Ports

| Port | Role |
|---|---|
| 28969 | lobby/auth (`server319.lsg`) |
| 28971 | game server (UDP) |
| 29000 | ring bridge bind port (the client's `localhost` traffic is redirected here) |

Only one instance of each may run at a time. The runner kills stale processes on
start, but check with:

```powershell
Get-Process codol1649370-offline -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'server319.lsg|server1649370.gameserver|ring_bridge_1649370' }
```

## 3. Run one match (recommended)

```powershell
python tools/run_match.py --name demo --seconds 75 --match-duration 45 --screenshot-at 20,35
```

What it does, in order:

1. kills stale client/server processes;
2. starts `server319.lsg` on 28969;
3. starts `server1649370.gameserver` on 28971 with the baseline snapshot and
   `--oob-command disconnect --match-duration 45`;
4. launches the client (`tools/launch_1649370.py --full --local-profile ...`);
5. waits for `engine-init`, drives the login state machine, blocks ring-a,
   installs the refresh hook;
6. starts `ring_bridge_1649370.py forward` on 29000 and issues `connect`;
7. samples the client state at t=20/35/50/65 s and captures frames at the
   times given by `--screenshot-at`;
8. writes `runs/<name>-summary.json` and `runs/<name>-tNN.png`.

Expected result (verified): `states 9 -> 10 -> 10 -> 0`.

## 4. Run it by hand

```powershell
# 1 lobby/auth
python -m server319.lsg --cert runs/20261020-live-derived01/tls/auth.crt `
  --key runs/20261020-live-derived01/tls/auth.key --port 28969 `
  --log runs/manual-lsg.jsonl --seconds 3600 --allow-auth-tls

# 2 game server (60 s match)
python -m server1649370.gameserver --port 28971 --log runs/manual-gs.jsonl `
  --delay-send 10 --gamestate-source native `
  --snapshot-file runs/snapshot-hybrid-empty-actors.bin `
  --snapshot-delay 20 --snapshot-seq 1000 --snapshot-repeat 120 --snapshot-interval 1.5 `
  --oob-command disconnect --match-duration 60

# 3 client
python tools/launch_1649370.py --full --seconds 400 --local-profile `
  --loopback-tcp-guard --local-auth-lsg --reuse-runtime 20261023-codex-delay-a2 `
  --name manual --trace-files

# 4 login + bridge (after engine-init appears in the launch log)
python tools/drive_login_state_machine.py --set-ui-state 1 --ticks 40 --interval 0.4
python tools/ring_bridge_1649370.py ring-a-drain block
python tools/install_refresh_hook.py --install
python tools/ring_bridge_1649370.py forward --target 127.0.0.1:28971 `
  --seconds 75 --adr-type 2 --fake-stats --keepalive --bind-port 29000 `
  --reliable-until-state 0 --max-events 800
python tools/ring_bridge_1649370.py connect --address 127.0.0.1:29000 --settle 2

# 5 read the state / take a screenshot
python tools/ring_bridge_1649370.py status
python tools/cbuf_command.py --command screenshot
```

## 5. Reading the client state

The state lives at `0x76446B0` in the client process (read it with
`ring_bridge_1649370.py status`). Meaning observed on this build:

| State | Meaning | Frame |
|---|---|---|
| 0 | disconnected / lobby | real lobby UI |
| 5 | connecting | - |
| 8 | loading handshake | - |
| 9 | map loading | **loading screen** with map, minimap, `等待玩家数据` |
| 10 | network active (in match) | black (cgame has no scene data) |

So: **state 9 shows a real loading screen, state 10 is black** - the visible world
is the open item described in `RELEASE.md`.

## 6. Where the evidence lives

| Kind | Path |
|---|---|
| Server JSONL log (every OOB / gamestate / snapshot / command) | `runs/<name>-gs.jsonl` |
| Runner summary (steps, samples, frame stats) | `runs/<name>-summary.json` |
| Frames | `runs/<name>-tNN.png` |
| Experiment records (one JSON per experiment) | `evidence/experiments/20261023-codex-*.json` |
| Protocol notes | `docs/SNAPSHOT-FORMAT.md` |

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| `engine never initialised` | client log `runs/<name>-launch.out`; make sure no other instance holds the runtime |
| state never leaves 5 | lobby/auth not running, or the bridge was started after `connect` |
| state 9 forever | the snapshot body was rejected - try the baseline body first |
| client process disappears | a malformed snapshot carried bad playerstate values; revert to the baseline body |
| `XBOXLIVE_CANTJOINSESSION` | configstrings must not be placed in slots 13/18 |
| `Com Error 1124` | the gamestate is missing the 10-bit alias + 11-bit recipe count |
| map override disconnects | that map has no fastfiles in this resource set (only `mp_cross_fire` ships) |

## 8. Safe changes vs. risky ones

**Safe**: server-side parameters, snapshot bodies, configstrings, logging,
runner defaults.

**Risky**: client breakpoints. Hot or mid-function addresses (`0x4475F0`,
`0x471B9E`, `0x471C5C`) silently break the run (state 8, no traces). Use only the
addresses listed as safe in `docs/SNAPSHOT-FORMAT.md` section 6.
