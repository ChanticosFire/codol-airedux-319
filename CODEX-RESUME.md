# Codex continuation — 2026-10-20

User asked to fix in-game error 100 following HANDOFF-TO-CODEX.md.
User agreed to restart Codex as administrator once preparation is complete.

## Changes ready for elevated validation

- `server319/auth.py`: add numeric `member_position`, `estimated_wait_time`,
  `next_poll_after`, all zero. This is a candidate fix, NOT verified in 1649370.
  Source: `他人文件参考/_CURRENT_STATE(1).md` lines 751–780: the 1604220
  queue parser requires all three before ticket processing; missing fields
  stop connection progression. Keep other response fields unchanged to isolate it.
- `tools/patch_auth_bypass.py`: each existing observation now records `lobby`
  from the SAME patched PID (netobj, conn, ready, UI state/error, object A/B).
  Unreadable memory is null, not zero. Address meanings remain candidates.
- `tools/run_session.ps1`: fail before starting servers when not elevated.
- `server319/test_auth.py`: queue fields tested after JSON wire round-trip.
  `python -m unittest server319.test_auth`: 10 passed.
  `python -m py_compile tools/patch_auth_bypass.py`: passed.

## Critical evidence correction

`runs/20261020-session06/netfields.py` launches a NEW game without the Auth
patch. Thus its zero connection pointer does NOT prove that the patched,
successfully authenticated session has no connection object. Other probe_anchor
tools also launch separate games. HTTP 200 alone is not client Auth acceptance.
`lsgobj.json` has no modules, so its absent dump is not proof of zero globals.

## Next action

1. Check the current token is Administrator (previous Codex token was false).
2. From `319`, run:

   `pwsh -NoProfile -File tools/run_session.ps1 -RunId 20261020-codex-queue01 -Seconds 60`

3. Inspect auth.jsonl, lsg.jsonl, and SAME-PID lobby/tcp samples in patch.json.
   Verify whether the queue change enables the first LSG connection. Do not
   declare the game fixed just because a TCP connection appears.
4. If needed, compare against a response omitting just these three fields.
5. Current LSG implementation is ONLY a capture scaffold: HTTP replies 404;
   plaintext branch captures a frame then closes. Actual lobby protocol is not
   implemented, so a later protocol failure is expected even if Auth advances.
6. Do not force UI success using the jump table (already failed in DS tests).

## Tool/environment notes

REA opened original staged executable SHA256
36997674b18f2896de5e9d755686f6922af10708f355175714058d0a0172b537.
Native analysis failed: no configured Ghidra/IDA/Hopper provider. Do not repeat
setup or install unrelated runtimes; existing Capstone/probe tools can be used.
No games or servers were started this turn; original client files unchanged.
No Git commit created. `319` is the Git repository (parent directory is not).

## Secondary hypotheses (not changed)

Reference archive `服务端.zip` authchan.py uses auth_task=request+1 and code=700;
current server uses request value and code=0. Reference also has structured
tickets/extended_data. These are cross-version leads, not established fixes.
