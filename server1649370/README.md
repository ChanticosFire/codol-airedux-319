# server1649370

A from-scratch game server for **CODOL Build 1649370** (3.19.26.22, the final
shutdown build). It does not depend on the 2697 dedrun server. The client
accepts its handshake, gamestate and snapshot, but a server-driven visible
`mp_cross_fire` match has not yet been demonstrated.

## What works

| Capability | Status |
|---|---|
| OOB handshake (`getchallenge` / `connect` / `stats`) | working |
| Native gamestate (map, gametype, configstrings, checksum feed) | working |
| Snapshot delivery, client reaches network state 10 | working |
| Map selection (`--gamestate-map`) | working |
| OOB `disconnect` after `--match-duration` | working |
| Return to network state 0 | working |
| Full server logging / observability | working |
| Visible `mp_cross_fire` world driven by this server | open |

## Current acceptance criterion

Network state 10 only proves that the handshake finished. The target is
`ui_state` (`0x84ABA50`) **different from 5** plus a screenshot showing
`mp_cross_fire`. The current server path can hold an entity count of 1 while
network state is 10, but `ui_state` remains 5 with a loading spinner.

The 2021-08 real-match demo renders `mp_crash_tropical` in this same build.
Its record format and snapshot bytes are being used to reconstruct the missing
server-driven loading transition. See `docs/NEXT-SESSION.md` and
`docs/SNAPSHOT-FORMAT-VERIFIED.md` for the verified state.


## Components

| File | Role |
|---|---|
| `gameserver.py` | UDP game server: OOB commands, gamestate, snapshots, server commands, OOB end-of-match |
| `native_gamestate.py` | Builds the 1649370 gamestate (map, gametype, configstrings, checksum feed) |

Companion processes (see `../tools/`):

- `server319.lsg` - the auth/lobby side (must be online before login);
- `tools/ring_bridge_1649370.py` - bridges the client's local ring traffic to the
  game server (`forward` + `connect`);
- `tools/launch_1649370.py` - launches the client with the offline profile and
  optional breakpoints.

## Quick start

```powershell
# 1) lobby/auth side
python -m server319.lsg --cert runs/.../auth.crt --key runs/.../auth.key --port 28969 --allow-auth-tls --seconds 3600

# 2) game server: 60-second match, then automatic disconnect
python -m server1649370.gameserver --port 28971 --delay-send 10 ^
  --gamestate-source native --snapshot-file runs/snapshot-hybrid-empty-actors.bin ^
  --snapshot-delay 20 --snapshot-seq 1000 --snapshot-repeat 90 --snapshot-interval 1.5 ^
  --oob-command disconnect --match-duration 60

# 3) client
python tools/launch_1649370.py --full --local-profile --local-auth-lsg ^
  --reuse-runtime 20261023-codex-delay-a2 --name match

# 4) bridge + connect (after the client is up and logged in)
python tools/ring_bridge_1649370.py forward --target 127.0.0.1:28971 --bind-port 29000 --adr-type 2 --fake-stats --keepalive
python tools/ring_bridge_1649370.py connect --address 127.0.0.1:29000
```

Observed network sequence: `state 5` -> `state 9` -> `state 10` -> after
`--match-duration` seconds the server sends OOB `disconnect` -> `state 0`.
This sequence alone does not establish that a visible match started or that
the lobby UI returned; inspect `ui_state` and a screenshot for those claims.

## Diagnostics

- server log (JSONL): every OOB, gamestate, snapshot and command with timestamps;
- client-side `snap_trace` breakpoints (`--breakpoint 0x471D80:SnapTraceEntityLoop`
  and friends) record the parser cursors into the run's `events.jsonl`;
- `tools/ring_bridge_1649370.py status` reports the live client state machine.

## Evidence

All experiments are archived under `evidence/experiments/` as JSON records
(`20261023-codex-*.json`), each with the exact recipe, measurements, and
conclusion.
