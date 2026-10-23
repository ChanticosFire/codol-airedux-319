# playerState measurement log

Every row is a real experiment: a constructed body, the ps block the client
actually consumed, and whether the client accepted it. This table is the most
useful artefact for whoever continues, because the numbers **do not match any
simple model yet** - that mismatch is itself the finding.

`ps bits` is measured as `actors entry bit - 1308` using the `SnapTracePlayerState`
and `SnapTraceActors` breakpoints. `state` is the network state after the
snapshot was processed (10 = accepted, 9 = rejected).

| # | body | construction (V, distance, field) | ps bits | state | evidence |
|---|---|---|---|---|---|
| 1 | `snapshot-hybrid-empty-actors.bin` | `has-ps = 0` (whole block skipped) | **1** | **10** | `20261023-codex-baseline-geometry.json` |
| 2 | `snapshot-single22.bin` | `V=22, d=23, codec 11, value 0` | **29** | **10** | `20261023-codex-ps-body-stable-exact.json` |
| 3 | `snapshot-nz1.bin` | `V=22, d=23, codec 11, value 0x100` | 32 | 9 | `20261023-codex-nz1-32bits.json` |
| 4 | `snapshot-cmdtime.bin` | `V=1, d=2, codec -97, value 1000` | 24 | 9 | `20261023-codex-cmdtime-rejected.json` |
| 5 | `snapshot-c58-v45.bin` | `V=1, d=1, codec -58, 45 zero bits` | 55 | 9 | `20261023-codex-codec58-variable-length.json` |
| 6 | `snapshot-c58-f32-30.bin` | `V=1, d=1, codec -58, 30-bit value` | 61 | 9 | `20261023-codex-codec58-45bits.json` |
| 7 | `snapshot-trio2.bin` | three records (13/14/22), all zero | 81 | 9 | `20261023-codex-zero-gate-one-bit.json` |
| 8 | `snapshot-pad20.bin` | record 22 + 20 zero pad inside ps | (client died) | crash | `20261023-codex-padded-body-crashes.json` |
| 9 | earlier `V=9, d=1` | one step per record | 68 | 9 | `20261023-codex-tail-geometry-needed.json` |
| 10 | earlier `V=23, d=1` | one step per record | 69 | 9 | `20261023-codex-origin-cost-69.json` |
| 11 | `snapshot-jump23-a.bin` | `V=23, d=23, codec 11, value 0` | 54 | 9 | `20261023-codex-walk-model-confirmed.json` |
| 12 | `snapshot-v22.bin` | `V=22, d=23, codec 11, value 0` | 56 | 9 | `20261023-codex-cost-model-validated.json` |

## What the numbers say

- **Row 1 and 2 are the only accepted bodies.** Everything that carries a
  non-zero value is rejected or crashes.
- **Rows 2, 11 and 12 conflict.** All three are `V=22`-like, `d=23`, codec 11,
  value 0 - yet they measure **29, 54 and 56 bits** and only row 2 is accepted.
  The bodies differ only in how the value was written (zero gate vs a 45-bit zero
  payload), so **the bit layout we emit for "zero" is not identical in those
  cases** - the encoder changed between rounds (the zero-gate fix landed in
  round 126).
- **Rows 5 and 6 show `-58` is variable length** (39 payload bits for zero, 45 for
  a large value), and **any non-zero `-58` kills the client**.
- **Rows 3 and 4 do not fit the cost model** (32 and 24 bits against predictions
  of 40 and 52), which means either `distance` or the landing index is not what
  the model assumes for those bodies.

## The one thing to try next (if anyone continues)

Rebuild **row 3** with the **current** encoder (which now emits the corrected
zero-gate and plain-LSB forms) and re-measure. Rows 11/12 exist because the
encoder changed underneath the measurements, so the table contains
**apples-to-oranges comparisons**; a single re-measurement of every row with one
fixed encoder version would settle whether the cost model holds.

Do that **with `tools/selfcheck.py` green first**, and **assert delivery** before
reading any trace.
