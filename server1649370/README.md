# server1649370

A from-scratch game server for **CODOL Build 1649370** (3.19.26.22, the final
shutdown build). It does not depend on the 2697 dedrun server: the client
performs its own handshake, receives a native gamestate and a snapshot, loads
`mp_cross_fire`, sits in the match, and is sent back to the lobby at the end of
the configured match duration.

## What works

| Capability | Status |
|---|---|
| OOB handshake (`getchallenge` / `connect` / `stats`) | working |
| Native gamestate (map, gametype, configstrings, checksum feed) | working |
| Snapshot delivery, client reaches **state 10** (in match) | working |
| Map selection (`--gamestate-map`) | working |
| Automatic end of match (OOB `disconnect` after `--match-duration`) | working |
| Return to lobby (client back to **state 0**) | working |
| Full server logging / observability | working |
| Visible world (entities / camera) | **not possible on the wire** - see below |

## Known limitation: the visible world

The client's snapshot parser has a global stream-error flag at `[cl_stream]`.
The entity loop (`0x471D80`) has no count-based exit - it only stops when it
reads past `length`, which sets that flag. Later blocks (`0x471980` playerState,
`0x471010` actors, `0x471560`, `0x4475F0` glass) reset their own cursors before
running, but the flag stays set, and `0x4724A5` (`cmp [esi], edi`) rejects the
snapshot. That is why every body with an entity table (`A=1`) ends at **state 9**,
while the empty body (`A=0`, 167 bytes) reaches **state 10**.

Evidence chain: `evidence/experiments/20261023-codex-error-persists.json`,
`20261023-codex-count-positive-error.json`, `20261023-codex-a1-count0.json`.

A visible world would require a client-side change; it is out of reach from the
protocol alone.

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

Expected sequence: `state 5` -> `state 9` (map load) -> **`state 10`** (in match)
-> after `--match-duration` seconds the server sends the OOB `disconnect` ->
client returns to **`state 0`** (lobby).

## Diagnostics

- server log (JSONL): every OOB, gamestate, snapshot and command with timestamps;
- client-side `snap_trace` breakpoints (`--breakpoint 0x471D80:SnapTraceEntityLoop`
  and friends) record the parser cursors into the run's `events.jsonl`;
- `tools/ring_bridge_1649370.py status` reports the live client state machine.

## Evidence

All experiments are archived under `evidence/experiments/` as JSON records
(`20261023-codex-*.json`), each with the exact recipe, measurements, and
conclusion.
