# Phase summary: 1649370 self-hosted server

This document freezes the state of the 1649370 work so far. It records what is
**delivered and reproducible**, what is **not delivered**, and **exactly what a
future attempt needs** to continue.

## 1. Delivered (reproducible, with evidence)

| Item | Command / artefact |
|---|---|
| Game server | `python -m server1649370.gameserver --port 28971 ...` |
| Lobby/auth server | `python -m server319.lsg --port 28969 ...` |
| One-command match run | `python tools/run_match.py --name demo --seconds 75 --match-duration 45 --screenshot-at 20,35` |
| Verified result | steps all true; **state 9 -> 10 -> 10 -> 0**; timed frames written |
| Match end + lobby return | `--oob-command disconnect --match-duration N` (the client shows the disconnect dialog, returns to the lobby at state 0) |
| Map override | `--gamestate-map NAME` now propagates into **configstring 0**, `connectResponse` and the start log |
| Observability | JSONL server log (every OOB / gamestate / snapshot / command), `snap_trace`, `decide`, `ps_field` probes, frame statistics |
| Documentation | `RELEASE.md` (capabilities), `docs/RUNBOOK.md` (operations), `docs/SNAPSHOT-FORMAT.md` (protocol), this file |
| Evidence | 115+ JSON records under `evidence/experiments/` |

## 2. Not delivered

**A visible, playable world.** The client reaches network state 10 but the frame
is black: cgame has no scene data. Two independent blockers:

1. **playerState content** - only an **all-zero** playerState is accepted
   (state 10 reproducibly). Any non-zero value is **rejected** (state 9) or
   **crashes** the client.
2. **Per-entity payload** - the entity table parses (`entity_count = 1`) but the
   per-entity field set has never been produced, and the entity + playerState
   combination crashes the client.

## 3. What is known for certain (with evidence)

### Protocol framing
- Baseline body: `runs/snapshot-hybrid-empty-actors.bin` (167 B) reaches state 10
  because its playerState block is **one bit** (`has-ps = 0`).
- Block order in the parse chain `0x4723B9..0x4724A0`:
  `0x671D80` -> `0x471D80` (entities) -> `0x471980` (playerState) ->
  `0x471010` (actors) -> `0x471560` -> `0x4475F0` (glass).
- The snapshot is rejected at **`0x4724A7`** iff **`stream_error != 0`**; the
  other two checks (`struct_3bd0 != 0`, `field_54 != 0`) pass in our runs.

### playerState delta
- `0x670FF0`: read 1 bit (0 -> return); read the index width (**5 bits** for 24
  fields) = **`V` = target position**; read `distance`; **copy** fields
  `0..distance-2` without reading bits; **decode** the landing field at
  `distance-1`; **loop until the position reaches `V`**. Therefore
  **`distance = V + 1`** lands on `V` in one record.
- `0x670CB0`: `distance` = 1 for a single `1` bit, else `1 + sum(3-bit chunks)`
  with chunk max 7.
- Cost model (validated exactly): `ps_bits = 14 + distance_bits(d) +
  field_bits(codec) + 1`; the working body measures **29** bits, the model
  predicts **29**.
- `0x670B15`: a positive-width codec reads **1 gate bit** (0 -> value 0) then
  **N plain LSB-first bits**. (The 3.3.3.3 "remainder-first" form does **not**
  apply to this build.)
- `-97` (offset 0, `commandTime`) costs `1 + 32` bits; codecs 10/11 are wide
  (27/28 bits) fields.
- `-58` (first field) is variable-length and **kills the client** if written
  non-zero.

### Field tables
- **`0xDA8520`** is the table the ps delta decoder actually indexes (first entry
  `offset 0 / codec -97`). **`0xDA63E8`** is a **different** table that this
  project mistakenly used for most of its life.

## 4. What a future attempt needs

**Route A (recommended): a captured snapshot.** Any real server snapshot for this
build would let the decoder be driven with known-good bytes, turning the problem
from inference into comparison. Nothing else unblocks it this cheaply.

**Route B: interactive debugging.** The decoder is understood at the instruction
level (`0x670FF0`, `0x670CB0`, `0x670B15`, `0x6701D0`, `0x471980`). A debugger
session that single-steps a real snapshot through `0x471980` and records each
field codec actually decoded would produce the missing semantics directly.

## 5. Tooling hazards (learned the hard way)

- Patching `int3` into **hot or mid-function** addresses silently breaks the run
  (`0x4475F0`, `0x471B9E`, `0x471C5C`). Safe addresses are listed in
  `docs/SNAPSHOT-FORMAT.md` section 6.
- **Linear disassembly stops at invalid bytes**: always use `skipdata=True` when
  scanning for call sites, otherwise real call sites are missed (this produced a
  wrong "indirect dispatch" conclusion once).
- **Assert delivery before analysing**: forward summary exists, `snap_trace`
  records > 0, and the client run-directory count did not increase. Two recent
  sessions were wasted by skipping this.
- `[stream+0x24]` is **not** the bit cursor (the ps header writes `last` there,
  and the actors block reuses it as the actor index).

## 6. Bottom line

The self-hosted server is **complete and reproducible** for: handshake, gamestate,
snapshots that the client accepts (state 10), a match that ends, and a return to
the lobby - all observable through logs and probes.

The **visible world** remains blocked on **content encoding**, and the honest
assessment is that further black-box attempts have a poor return: the last
fourteen rounds produced solid protocol knowledge but no accepted non-zero
content.
