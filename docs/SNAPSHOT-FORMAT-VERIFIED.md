# Snapshot format — verified only

Every statement in this file was **measured on build 1649370** or **read out of its code**.
Anything that was assumed and later falsified is listed in §8 so it is not reintroduced.

Addresses are virtual addresses in `codol1649370-offline.exe` (image base `0x400000`).

---

## 1. Snapshot body header (verified against the cols writer)

| offset | size | field | value we send |
|---|---|---|---|
| 0 | 1 | `svc_snapshot` | `0x00` |
| 1 | 4 | `serverTime` (LE) | `0x00011A08` (72200) |
| 5 | 1 | `delta_distance` | `0x00` |
| **6** | **1** | **`flags`** | **`0x0C`** (cols writes `0x08` for a baseline, `0x00` otherwise) |
| 7 | … | bit fields (see below) | |

Bit fields after the header bytes:

- 1 bit — no prior playerState (`0`)
- 1 bit — transmit origin/velocity (`1`)
- **8 bits — `last_changed + 1`**
- 1 bit — field gap `+1` from `-1`
- 1 bit — `-97` codec, absolute LE32
- 4 bytes — `commandTime` (LE)

The `8 bits` for `last_changed` is the single most consequential difference from the
3.3.3.3 generation, which used a different width.

**Note**: we send `flags = 0x0C`; setting it to `0x08` (exactly what cols writes for a
baseline) **does not change the client's behaviour** — see §7.

## 2. Content blocks — there are exactly FIVE

A whole-`.text` scan for calls to each block entry found **exactly one call site per block**,
all inside the dispatcher at `0x4723C4..0x4724CD`:

| call site | block entry | block |
|---|---|---|
| `0x4723DD` | `0x471D80` | entities |
| `0x472401` | `0x471980` | playerState |
| `0x472424` | `0x471010` | actors |
| `0x472445` | `0x471560` | unidentified |
| `0x4724A0` | `0x4475F0` | glass |

`0x671D80` is **only the header parser** — it never calls any content block.

## 3. Entity list (`0x671650`)

Entry gate: `0x471DA3` calls `0x671650`; if it returns 0 the whole block is skipped
(`je 0x471E88`). The call at `0x4723DD` itself is unconditional.

Inside `0x671650`:

| address | action |
|---|---|
| `0x671650` | `memset(0x7859358, 0, 0x1204)` — clear the id list |
| `0x671661` | `memset(0x785955A, 0xFF, 0x1001)` |
| **`0x671678`** | **read 1 bit** — gate 1. **This bit is body bit 1307.** |
| **`0x671685`** | **read 1 bit** — gate 2. **Body bit 1308.** |
| `0x67168F` | `call 0x66ED70` — read the count |
| `0x671698` | `mov [0x7859558], al` — **the count is a BYTE at `buffer[164]`** |
| `0x6716A1` | `push 0xC` / `call 0x66EC30` — **12-bit entity id** |
| `0x6716AD` | `mov word [ecx*2 + 0x7859358], ax` |

### 3.1 The id is NOT a contiguous 12-bit slice

Measured: with body bytes 163..166 = `18 01 FA 1F`, bits 1309..1320 read `000100000000` (= 8),
**yet the client stored `0x0FD0` = 4048**.

Verified explanation: the id is assembled as

```
id = ((byte163 >> 5) & 7) | (byte165 << 3) | ((byte166 & 1) << 11)
```

which with those bytes gives `0 | (0xFA << 3) | (1 << 11)` = **`0x0FD0`** — an exact match.

Why: `0x66EC30`'s multi-byte path resumes at `[+0x1C]` (the **byte cursor**), which the count
reader had already advanced from 164 to 165. **The bit reader therefore skips byte 164.**

Controlled test: writing `byte163 = 0x18, byte164 = 0x01, byte165 = 0x01, byte166 = 0x1E`
produced **`eax = 8`** at the store — the recipe works.

**Caveat**: bytes 165 and 166 are also data for the blocks that follow, so changing the id
by blind byte edits breaks the tail and the client exits. The id must be changed together
with a regenerated tail.

## 4. Per-entity payload (`0x471DE3` …)

| address | action |
|---|---|
| `0x471DE3` | index from the frame clock; `edi = &entityRing[i]`, stride **`0x34`** |
| **`0x471E03`** | **read 1 bit — the per-entity `changed` flag** (body bit 1329 for our body) |
| `0x471E0E` | flag = 1 → read N bits, then **copy 52 bytes** into the entity ring slot |
| **`0x471E4A`** | **flag = 0 → `call 0x671700`** — the delta decoder |

### 4.1 The delta decoder `0x671700`

`0x671700` handles **exactly one mode operation** per entity per snapshot (its exit at
`0x671A0D` is a bitset mark, then it returns).

**Mode selector**:

| address | action |
|---|---|
| `0x67170A` | `[ebp-4] = 3` initially |
| `0x671714` | mode 3 → selector; mode 4 → selector; anything else → return 0 |
| `0x671722` | read 1 bit; if 1 → read 2 bits, **mode = value + 1** |
| `0x67173F` | else read 1 bit; if 1 → read 2 bits, **mode = value + 5** |
| `0x67175B` | else read 1 bit; if 1 → **mode = value + 9**, else **mode = value + 13** |
| `0x671782` | `[ebp-4] = mode` |
| `0x671791` | `(mode-1) > 12` → return 1 |
| `0x67179A` | `jmp [mode-1 * 4 + 0x671B2C]` |

**Jump table at `0x671B2C` (13 dwords)**

| mode | handler | behaviour |
|---|---|---|
| 1 | `0x671890` | **commit**: writes `[edi+0x10]`, `[edi+8]`, `[edi+0x30]`, `[edi+0x18]`, then **three floats at `+0x24`, `+0x2C`, `+0x28`** |
| 2 | `0x671833` | reads bits |
| 3 | `0x6717A1` | **accumulator**: read 11 bits → `[esi+0x24]` |
| 4 | `0x6717B5` | **accumulator**: read one `-97` value → `[esi+0x28]` |
| 5 | `0x671B21` | return 1, no field |
| 6,7,8,9,10 | `0x671979`, `0x6719E8`, `0x6718D2`, `0x6719AA`, `0x6719B8` | 8 is a partial commit; 6,7,9,10 copy |
| 11,12,13 | `0x6717C7`, `0x6717FD`, `0x67193C` | read bits and write `[edi]` |

**A delta is therefore a sequence of mode-coded operations**, not a field loop: modes 3/4
fill stream scratch, modes 1/8 commit into the entity struct.

**Demonstrated**: a mode-1 delta wrote real floats into the entity struct —
`[edi+0x24] = 3.5806`, `[edi+0x28] = 1.0`, `[edi+0x2C] = 0.1`.

### 4.2 Position components

Each of the three components inside mode 1 is read **inline** by `0x6715D0`, `0x6714D0`,
`0x671550`:

- **gate (1 bit)** — 0 means “component unchanged”
- **scale (1 bit)** — 1 selects the constant at **`0xDB1118` = 5.0**, 0 selects 1.0
- **value (5 bits)**

So a component costs 7 bits and moves the entity by `value × 1.0` or `value × 5.0`.

## 5. Cursors and position fields (stream struct)

| offset | meaning |
|---|---|
| `+0x08` | buffer pointer (`stream + 0x34` for the embedded body buffer) |
| `+0x0C` | alternate buffer (0 in our runs) |
| `+0x10` | bound (131072) |
| `+0x14` | body length (172 for our body) |
| `+0x18` | window start (0) |
| **`+0x1C`** | **byte cursor** (advanced by whole-byte readers) |
| **`+0x20`** | **absolute bit position** (“next bit to read”) |
| `+0x24` / `+0x28` | scratch for the mode 3 / mode 4 accumulators |

`0x447190` (single bit) and `0x66EC30` (N bits) both work from `[+0x20]`; `0x66ED70` reads a
whole byte and advances only `[+0x1C]`.

Measured at the entity block: `[+0x1C] = 164`, `[+0x20] = 1307`, `[+0x14] = 172` — consistent
with the reader's own rule (`[+0x20] = (old_byte × 8) + bit_offset`).

**The first bit read of a snapshot is at bit 243**, i.e. the header consumes ~30 bytes of
byte/string data before any bit field.

## 6. Acceptance oracle — read this before claiming anything

| value | meaning |
|---|---|
| `net_state` (`0x76446B0`) == 10 | **only** means the network handshake finished. **It is NOT “in match”.** |
| **`ui_state` (`0x84ABA50`) == 5** | **the loading screen** |
| **loading object (`[0x8269774]`) != 0** | **the frontend still believes it is loading** |

A screenshot at `net_state = 10` **with one entity** showed **a black frame and a loading
spinner**: see `runs/codex-r231-shot.png`.

`0x803780` drives `ui_state`: while `[0x8269774]` is non-null the loader is kept; when it
becomes null `ui_state` is cleared to 0 and loading is dismissed.

The loading object is a C++ instance (vtable `0xD599DC`, first slot `0xB82850` is the deleting
destructor, destructor body `0xB824F0`, instance ≥ `0x4F8` bytes) and it is **partially
initialised**: it contains `0xBAADF00D` (the debug-heap uninitialised marker).

## 7. What we tried against the loader, and what happened

| lever | result |
|---|---|
| core snapshot contents (playerState, entity count, id, delta, position) | all accepted, **loader never cleared** |
| `flags` `0x0C` → `0x08` (exact baseline value) | **no change** |
| send an entity-free snapshot first, then an entity snapshot | **`net_state` 10 and count 1 coexist** — but `ui_state` stays 5 |
| all-five-block coverage | already the case |

## 8. Falsified statements — do not reuse

1. “`state 10` means the snapshot was accepted / the world is loaded.” **False.**
2. “`0x671D80` calls the entity block.” **False** — it is only the header parser.
3. “The entity block is never entered.” **False** — it runs; it decoded a count and an id.
4. “The entity id is bits 1309..1320.” **False** — it is the three-part assembly in §3.1.
5. “The snapshot has two independent cursors.” **False** — one position, two units.
6. “`PsField` (`0x6701D0`) is playerState-specific.” **False** — it is a generic field codec.
7. “1649370 has 14 snapshot sections.” **False** — it has 5.
8. “A NULL history at `0x47239A` skips the whole content pipeline.” **Partly false** — the gate
   is on the `bit == 1` branch; our bodies take the `bit == 0` branch and still proceed.

## 9. The open problem, stated precisely

Everything the server sends is accepted: the header parses, five blocks are entered, the entity
count becomes 1, an entity id is stored, and a mode-1 delta writes real floats into the entity
struct. **The client nevertheless keeps a loading object alive and never leaves `ui_state = 5`.**

That object is **partially initialised** (`0xBAADF00D` in two slots) and is at least `0x4F8`
bytes. **The next work item is to identify what fills those slots**, which requires either
symbolic information for this build or a memory-write breakpoint — neither of which the current
harness provides (it supports `int3` breakpoints at fixed addresses only).
