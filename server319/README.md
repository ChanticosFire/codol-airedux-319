# Build 1649370 server research scaffold

This is an independent, local service. It verifies four known Build 1649370
client files before opening a listener. Two modes exist:

- **capture** (default): a provisional little-endian 32-bit length envelope;
  records metadata for unknown frames and never fabricates a reply.
- **auth** (`--auth`): the HTTP/JSON `POST /auth/` endpoint that the 1649370
  client actually calls, implemented from captured wire data.

It has **no LSG/room/match/gameplay reply implementation** yet.

Run from `319`:

```powershell
python -m server319 --help
python -m server319 --client-dir 'E:\GAME\COD\使命召唤OL' --preflight
python -m unittest server319.test_server319 server319.test_auth
```

## Auth mode

```powershell
python -m server319 --client-dir .\runtime\client-1649370 --auth `
    --cert runs\<run-id>\tls\auth.crt --key runs\<run-id>\tls\auth.key `
    --port 4175 --seconds 180 --evidence runs\<run-id>\auth.jsonl
```

Observed on the client: HTTP `POST /auth/` with a JSON body
(`auth_task`/`iv_seed`/`title_id`/`identity`/`extra_data`), `Expect:
100-continue`, and a TLS handshake that only succeeds at TLS 1.0–1.2 with old
cipher suites (`ALL:@SECLEVEL=0`). The response shape and the `DW-*` headers
mirror the captured reference; ticket bytes are **zero-filled synthetic
values** because the real BD ticket key/magic are unknown for this Build. The
client reaches the lobby only after a runtime patch that skips its ticket
verifier, so this endpoint is a protocol scaffold, not proof of authentication.

Evidence records metadata only (request line, headers, body length and
SHA-256); it never writes ticket bytes, credentials or peer addresses.

## Capture mode

`python -m server319 --client-dir .\runtime\client-1649370 --port 0 --evidence .\runs\<run-id>\server.jsonl`
starts a 127.0.0.1-only capture listener on a free port after the same
preflight and requires a completed stage receipt. The JSONL evidence log
records a SHA-256 and length, never payload bytes, tickets, passwords, peer
addresses, or arbitrary exception text. No client is launched and no
third-party scripts are imported.
