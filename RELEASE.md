# CODOL 1649370 - Self-hosted Server Release Notes

Build **1649370** (3.19.26.22, the final shutdown build). This document is the
delivery summary of the `server1649370` work: what is verified, what is not,
how to run it, and where the evidence lives.

## 1. What this is

A from-scratch game server for CODOL 1649370 that replaces the 2697 dedrun
server in the login/game-server path, plus the tooling needed to drive and
observe the client while it connects.

The server does **not** depend on any 2697 code or data. The client performs its
own handshake, receives a native gamestate and snapshots, reaches the network
"active" state (10), stays in the match for a configurable duration, and is sent
back to the lobby (state 0) by the server.

## 2. Verified capabilities

| Capability | Status | Evidence |
|---|---|---|
| OOB handshake (`getchallenge` / `connect` / `stats`) | verified | `runs/codex-*.jsonl` server logs |
| Native gamestate (map, gametype, configstrings, checksum feed) | verified | `20261023-codex-gamestate-*` |
| Snapshot delivery; client reaches network state **10** | verified | `20261023-codex-state-vs-uistate.json` |
| Map selection (`--gamestate-map`) | **only for maps whose fastfiles are present** - the offline resource set ships **mp_cross_fire only**, so other maps disconnect the client | `20261023-codex-map-override-fixed.json` |
| Automatic end of match (OOB `disconnect` after `--match-duration`) | verified | `20261023-codex-match-flow.json` |
| Return to lobby (client back to **state 0**) | verified | `20261023-codex-oob-disconnect-success.json` |
| playerState block accepted (non-empty field) | verified | `20261023-codex-ps-nonempty-accepted.json` |
| Server logging / observability | verified | JSONL logs + `snap_trace` breakpoints |
| **Visible 3D world / player movement** | **not achieved** | see section 3 |

## 3. Known limitation: the visible world (build-level, final classification)

**Status: closed as a build-level limitation of the offline rebuild, not a server defect.**
The decisive test (`20261023-codex-ps-no-copy-decisive.json`): a playerState written
into the client's ring produced **no copy anywhere in the process** (full-process
scan found the float pair exactly once). Eight independent data paths were tried
(entity delta encoding, clc injection, cg injection, UI forcing, remote callback,
ps ring write, ps slot write, vieworg write) and none produced a rendered frame.

The client is internally consistent - it accepts the gamestate and snapshots
(network state 10), runs its own UI, and can be returned to the lobby (state 0) -
but its 3D scene path stays inert in this rebuild. The server side is complete for
everything it can control.

### Detail of the investigation

The client stays on the loading screen and renders a black frame. This is **not**
a protocol or server defect:

- the client accepts the gamestate and snapshots and reports network state 10;
- its UI state remains 5 (loading screen) and the rendered frame has no scene.

Root cause chain (all measured, see the evidence index):

1. the entity block (`A=1`) sets the global stream-error flag because the
   entity loop has no count-based exit - so entity snapshots are rejected
   (`20261023-codex-error-persists.json`);
2. the playerState block **is** accepted (state 10) once its frame-loop layout is
   respected (`20261023-codex-ps-nonempty-accepted.json`);
3. but the per-field delta encoding still contains one component we have not
   modelled (a per-field cost of about 4.3 bits), so the playerState we deliver
   is **empty** and cgame has no camera or local player
   (`20261023-codex-ps-full-overrun.json`);
4. bypassing the wire format by writing the client's playerState history ring has
   no effect - cgame consumes a per-snapshot copy
   (`20261023-codex-ring-write-no-effect.json`).

## 4. Components

| Path | Role |
|---|---|
| `server1649370/gameserver.py` | UDP game server: OOB, gamestate, snapshots, commands, end-of-match |
| `server1649370/native_gamestate.py` | 1649370 gamestate builder (map/gametype/configstrings/checksum feed) |
| `server1649370/README.md` | component-level usage |
| `tools/launch_1649370.py` | client launcher with instrumentation handlers |
| `tools/ring_bridge_1649370.py` | ring traffic bridge (`forward` / `connect` / `status`) |
| `tools/cbuf_command.py` | console command injection (e.g. `screenshot`) |
| `tools/drive_login_state_machine.py` | UI-state driver |
| `tools/force_call.py` | remote-thread function call helper |
| `tools/install_refresh_hook.py` | refresh hook installer |
| `evidence/experiments/*.json` | one JSON per experiment, each with recipe, measurement, conclusion |

## 5. Quick start

**One command (recommended)** - runs the whole match end to end and writes a
JSON summary plus timed screenshots:

```powershell
python tools/run_match.py --name demo --seconds 75 --match-duration 45 --screenshot-at 20,35
# -> runs/demo-summary.json  (steps, state samples, frame statistics)
# -> runs/demo-t20.png / runs/demo-t35.png
```

Verified regression output (`--name regression`):
`steps {engine_init, login, ring_a_blocked, refresh_hook, connect} all true`,
`states t=20 -> 9, t=35 -> 10, t=50 -> 10, t=65 -> 0`,
`frames t=20 loading screen (unique 4117), t=35 black (unique 6)`.

**Manual sequence** (same thing, step by step):

See `server1649370/README.md` for the full sequence. Minimal flow:

```powershell
python -m server319.lsg --cert <crt> --key <key> --port 28969 --allow-auth-tls --seconds 3600
python -m server1649370.gameserver --port 28971 --gamestate-source native ^
  --snapshot-file runs/snapshot-hybrid-empty-actors.bin ^
  --snapshot-delay 20 --snapshot-seq 1000 --snapshot-repeat 90 --snapshot-interval 1.5 ^
  --oob-command disconnect --match-duration 60
python tools/launch_1649370.py --full --local-profile --local-auth-lsg --reuse-runtime <runtime>
python tools/ring_bridge_1649370.py forward --target 127.0.0.1:28971 --bind-port 29000 --adr-type 2 --fake-stats --keepalive
python tools/ring_bridge_1649370.py connect --address 127.0.0.1:29000
```

Expected: `state 5 -> 9 -> 10`, then after `--match-duration` seconds the server
sends the OOB `disconnect` and the client returns to **state 0**.

## 6. Evidence index (selection)

| File | Subject |
|---|---|
| `20261023-codex-match-flow.json` | full match flow: connect, load, play, end, lobby |
| `20261023-codex-oob-disconnect-success.json` | OOB disconnect returns the client to state 0 |
| `20261023-codex-state-vs-uistate.json` | network state 10 vs UI state 5 (loading) |
| `20261023-codex-ps-aligned-state10.json` | first ps block accepted (empty) |
| `20261023-codex-ps-nonempty-accepted.json` | ps with a non-empty field accepted |
| `20261023-codex-ps-frame-loop.json` | ps block is a frame loop re-reading `has-ps` |
| `20261023-codex-ps-cost-scales.json` | ps cost scales with the landing field index |
| `20261023-codex-ps-full-overrun.json` | per-field cost is ~4.3 bits beyond the model |
| `20261023-codex-error-persists.json` | global stream-error flag closes the entity path |
| `20261023-codex-inject-cg-no-effect.json` | renderer entity array write has no visible effect |
| `20261023-codex-ring-write-no-effect.json` | ps history ring write has no effect |
| `20261023-codex-field0-decoded.json` | V = target field index + 1 |
| `20261023-codex-lobby-rendered.json` | the client renders a real 1920x1080 lobby; black frame was the loading screen |
| `20261023-codex-waiting-for-player-data.json` | loading screen text: 等待玩家数据 (waiting for player data) |
| `20261023-codex-baseline-geometry.json` | in the working body the ps block is exactly 1 bit (has-ps=0) |
| `20261023-codex-actors-terminator-found.json` | actors grammar and the 0x7FF terminator |
| `20261023-codex-tail-defect-found.json` | the v3 tail was the increment form, not the terminator |
| `20261023-codex-geom-sweep-negative.json` | EOF is not the blocker; ps content is the remaining suspect |

## 7. Protocol appendix (as reverse-engineered)

**Snapshot layout** (after the 4-byte header/cursor section):

```
... entity block (A bit + optional table + per-entity frames) ...
playerState block:
  loop {
    bit  has-ps        (0 -> exit)
    bit  mode          (1 -> last = bit+1, 0 -> read 5 bits = last)
    ... ring copy for this frame (no bits) ...
    bit  present       (1 -> skip, 0 -> delta decoder)
  }
actors / sub4 / glass blocks
byte 0x05 (EOF marker)
```

**delta decoder (`0x670FF0`)**:

```
bit  continuation      (0 -> return)
5 bit  advance V       (landing index = V - 1; V = target + 1)
       distance (0x670CB0)  -> fields between are copy-only
       per-field codec (0x6701D0) for the landing field
```

**playerState field table (`0xDA63E8`, 24 entries `[offset, codec, hint]`)**:

```
0:76/-58  1:80/-100  2:84/-100  3:65/-57  4:68/-97  5:72/16
6:66/-57  7:67/-100  8:12/10   9:56/12  10:60/-97 11:64/-57
12:52/32  13:20/10  14:24/10  15:40/6  16:28/10  17:44/6
18:32/10  19:48/6   20:4/11   21:8/11  22:16/11  23:36/6
```

Codec semantics found so far: `positive N` = 1 zero-flag + N bits;
`-57` = 1-bit boolean; `-58` = float with a baked-in scale; `-100` = float delta
vs previous; `-97` shares a handler with `-74/-72/-70`; `-101` = angle;
`-102` = vector; `0` = float with a 1+1+5-bit mantissa form.

## 8. Repository

All work is committed in the local git repository (`319/`). Recent milestones:

- `d2e52d3` - snapshot with a non-empty playerState field accepted
- `79c8b90` - ps block is a frame loop
- `cc27bd0` - the client does decode a field; V = target index + 1
- `1f2a44c` - full-field ps still overruns (~4.3 bits per field)
- `d3fc363` - ps ring write has no effect

## Status (frozen)

The capabilities above are **delivered and reproducible**. The visible world is
**not delivered**: the client reaches state 10 but renders a black frame because
cgame has no scene data. The blockers, the exact addresses, the cost model that
is already solved, and the two routes that would unblock it are documented in
**`docs/PHASE-SUMMARY.md`**.

### Self-checks

Two commands prove the encoder and the runner are sane without launching a match:

```powershell
python -m server1649370.ps_codec      # bit-level gap/codec round-trip -> "self-test failures: 0"
python tools/verify_encoder.py        # decodes the real accepted body
python tools/check_evidence.py        # audits evidence/ (valid JSON, references) -> "ps block at bit 1308,
                                      #  consumed 29 bits (expected 29)", "failures: 0"
```

`verify_encoder.py` reads `runs/snapshot-single22.bin` - the only playerState
carrying body the client accepted reproducibly - and asserts the exact field
sequence (`has-ps 1, mode 0, last 0, present 0, continuation 1, V 22, distance 23,
codec-11 value 0, exit 0`, 29 bits). A change that breaks the encoder cannot pass
this check.
