# CODOL 1649370 snapshot format - reverse-engineering notes

Everything below is **measured** or **read from the binary**, with the evidence
file named next to each claim. Anything not covered here is **unknown** and is
listed in section 7.

Addresses are file offsets for `codol1649370-offline.exe` (image base
`0x400000`).

## 1. Snapshot body layout (as observed)

```
[4-byte header section / cursors]      (see 0x471D80 caller)
[entity block]                          A bit (+ optional entity table) and per-entity frames
[playerState block]                     frame loop, see section 3
[actors block]                          see section 4
[glass block]                           short, ~14 bits in the working body
[0x05]                                  EOF marker byte
```

The whole body is bit-packed and little-endian at the bit level: bit `i` lives
in byte `i >> 3` at bit `i & 7`.

## 2. Working baseline

`runs/snapshot-hybrid-empty-actors.bin` (167 bytes = 1336 bits) reaches network
**state 10**. Measured block geometry with the two safe breakpoints
(`0x471980`, `0x471010`):

| block | entry bit | notes |
|---|---|---|
| playerState | **1308** | consumes **1 bit** (`has-ps = 0`) |
| actors | **1309** | consumes 13 bits (terminator, see section 4) |
| glass | ~1322 | ~14 bits |
| EOF | 1335 | last bit of the body |

So the baseline works because the **entire playerState payload is skipped**.

Evidence: `20261023-codex-baseline-geometry.json`.

## 3. playerState block (`0x471980`)

### 3.1 Frame loop

```
loop {
    bit  has-ps        ; 0 -> exit the whole block
    bit  mode          ; 1 -> last = bit+1 ; 0 -> read 5 bits = last
    ...  playerstate history ring copy for this frame (no bits read) ...
    bit  present       ; 1 -> skip the delta for this frame
                       ; 0 -> call the delta decoder (0x670FF0)
    if (stream error) exit
    loop back to the top
}
```

Evidence: `20261023-codex-ps-frame-loop.json`, `20261023-codex-ps-header-decoded.json`.

### 3.2 Delta decoder (`0x670FF0`)

```
bit   continuation     ; 0 -> return
5 bit value V          ; decoder position advance (not an absolute index)
       distance        ; 0x670CB0 (Elias-gamma style, `bits` argument = 3)
       copy 0x670D30   ; for fields strictly between old and new position (no bits)
       decode 0x6701D0 ; for the landing field (reads bits)
```

Evidence: `20261023-codex-delta-field-decoder.json`,
`20261023-codex-ps-codec-complete.json`.

**Measured cost**: landing index 0 → 28 bits; index 8 → 68 bits; index 22 → 69
bits. **Not linear**, so the decoder keeps reading past the landing field with
bounds that are **not yet identified**. Evidence:
`20261023-codex-ps-cost-not-linear.json`.

### 3.3 Field table (`0xDA63E8`, 24 entries, 12 bytes each: `[offset, codec, hint]`)

```
 0: 76 / -58    1: 80 / -100   2: 84 / -100   3: 65 / -57
 4: 68 / -97    5: 72 / 16     6: 66 / -57    7: 67 / -100
 8: 12 / 10     9: 56 / 12    10: 60 / -97   11: 64 / -57
12: 52 / 32    13: 20 / 10    14: 24 / 10    15: 40 / 6
16: 28 / 10    17: 44 / 6     18: 32 / 10    19: 48 / 6
20: 4 / 11     21: 8 / 11     22: 16 / 11    23: 36 / 6
```

The struct is `0x58` (88) bytes. Offsets map onto a conventional playerstate
layout (`origin` around 16/20/24, view angles around 40/44/48), but the
**field semantics are not confirmed**.

Evidence: `20261023-codex-ps-field-table.json`.

### 3.4 Codec semantics (`0x6701D0`, 46 codecs in a linear if-chain)

| codec | behaviour | evidence |
|---|---|---|
| positive N (6/10/11/12/16/32) | 1 zero-flag bit; if 0 the value is 0, else read N bits (`0x66FE30`) | `20261023-codex-ps-codec-complete.json` |
| `-57` (`0x6708E9`) | 1-bit boolean | same |
| `-58` (`0x6708BF`) | float with a baked-in scale `[0xD599EC]` via `0x66FE90` | same |
| `-100` (`0x6708AD`) | float delta against the previous value via `0x66FEE0` | same |
| `-97` (`0x67069C`) | shares a handler with `-74/-72/-70` (`0x670BBF`) | same |
| `-101` | float angle with rounding | same |
| `-102` | float vector | same |
| `0` | float with a 1+1+5-bit mantissa form | same |

## 4. actors block (`0x471010`)

Initialisation region `0x4710FC..0x471175` performs **no bit reads** (verified),
so there is no hidden header.

```
loop {
    bit  ; 1 -> next actor index = previous + 1
         ; 0 -> bit: 1 -> read 11 bits = absolute actor index
         ;           0 -> read  9 bits = index delta
    if (stream error) abort
    if (actor index == 0x7FF) -> END of block
    ... per-actor payload ...
}
```

The **terminator is actor index `0x7FF` (2047)**. This was verified on the
working baseline: its first 13 bits (`0111111111111`) decode as
`0, 1, 0b11111111111` = absolute index 2047.

Evidence: `20261023-codex-actors-terminator-found.json`,
`20261023-codex-tail-defect-found.json`.

## 5. What has been tried and rejected

| attempt | outcome | evidence |
|---|---|---|
| snapshots with the entity table (`A=1`) | entity loop has no count exit, sets the stream error | `20261023-codex-error-persists.json` |
| padding to terminate actors | actors ignores padding and reads to the end of the body | `20261023-codex-actors-no-exit.json`, `20261023-codex-tail-sweep-negative.json` |
| tail-length sweep (27/40/60/80/120/400) | no length accepted | `20261023-codex-geom-sweep-negative.json` |
| landing on a fixed-width field to avoid floats | still overruns (68 bits) | `20261023-codex-ps-cost-not-linear.json` |
| writing the client's playerstate ring / single slot | no effect, or the client crashes | `20261023-codex-ring-write-no-effect.json`, `20261023-codex-ps-slot-crash.json` |
| forcing the load-completion callback | no effect | `20261023-codex-force-call-loaddone.json` |
| writing a vieworg candidate | no effect | `20261023-codex-vieworg-write-no-effect.json` |

## 6. Tooling hazards (important for anyone continuing)

- Patching `int3` into **hot** or mid-function addresses **silently breaks the
  client** (observed with `0x4475F0`, `0x471B9E`, `0x471C5C`; the run stalls at
  state 8 or produces no traces).
- Safe breakpoints so far: `0x471D80`, `0x671700`, `0x4723DD`, `0x472810`,
  `0x671650`, `0x471980`, `0x471010`, `0x471A36`, `0x670FF0`, `0x6701D0`,
  `0x6710BB`.
- `[stream+0x24]` is **not** the bit cursor: the ps header writes `last` into it
  and the actors block reuses it as the actor index.

## 7. Open questions (what a real capture would settle)

1. The **bounds of the ps delta iteration** - why does landing on index 8 cost 68
   bits? Which value limits the loop?
2. The **per-actor payload format** inside the actors block (never reached with a
   working terminator + a real playerstate).
3. The **glass block** contents (only its length is known, ~14 bits).
4. The **field semantics** of the playerstate table (which offset means what).
5. Whether a coherent playerstate is required before the client leaves the
   loading screen (the loading text is `等待玩家数据` = waiting for player data).

**A captured snapshot from a real server would answer all five at once** - the
bytes could be replayed and compared instead of inferred.

## 9. Reference implementation available (cols)

`E:\GAME\COD\codol-airedux\cols` is a working Rust server for the **3.3.3.3**
generation and it contains a **complete snapshot writer** - the piece this
project had to hand-craft:

- `crates/protocol/src/game/snapshot/mod.rs` (136 KB, 30 submodules)
- entry points: `bootstrap`, `frame`, `equipped_frame`, `aimed_frame`,
  `player_frame`, `player_frame_with_motion`,
  **`player_frame_with_world(server_time, command_time, origin,
  establish_baseline, equipment, angles, world)`**
- one writer per block: `enemy.rs` (`write_enemy_entity`), `corpse.rs`,
  `hud.rs`, `glass.rs`, `props.rs`, `impact.rs`, `animal.rs`, ...

It cannot be copied verbatim (different generation), but it is the **reference to
port from**: its validation code encodes exactly the field semantics this project
is missing. The practical next step is to read
`player_frame_with_world` far enough to recover the **ordered block list and the
playerstate field order**, then map those field names onto the offsets in the
`0xDA63E8` table.

Evidence: `evidence/experiments/20261023-codex-cols-has-encoder.json`.
