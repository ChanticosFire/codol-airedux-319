# Build 1649370 server research scaffold

This is an independent, local service for Build 1649370. The top-level
capture/Auth CLI verifies four known client files before opening a listener.
The LSG CLI is a separate local listener, checks the same four anchors before
listening, and does not itself launch a client.

- **capture** (default): a provisional little-endian 32-bit length envelope;
  records metadata for unknown frames and never fabricates a reply.
- **auth** (`--auth`): the HTTP/JSON `POST /auth/` endpoint that the 1649370
  client actually calls, implemented from captured wire data.
- **lsg** (`server319.lsg`): raw LSG handshake and encrypted frame handler on
  the observed 4174 port. It derives session keys from the captured transcript
  and our synthetic Auth ticket; three Build 1649370 captures independently
  verify challenge, client MAC and AES plaintext. It sends one provisional
  `svc71/task4` response. Real client consumption of that response is untested.
  The prior memory-reading handler remains available as `--legacy-probe`.

It has **no room/match/gameplay reply implementation** yet.

Run from `319`:

```powershell
python -m server319 --help
python -m server319 --client-dir 'E:\GAME\COD\使命召唤OL' --preflight
python -m unittest discover -s server319 -t . -p 'test_*.py'
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
mirror the captured reference. [ticket.py](ticket.py) creates a structured
128-byte synthetic ticket with a Tiger checksum and a project-local 24-byte
session field. Captured Auth progress and LSG requests establish client
consumption in earlier diagnostic runs, but do not establish a playable lobby.

Evidence records metadata only (request line, headers, body length and
SHA-256); it never writes ticket bytes, credentials or peer addresses.

## LSG mode

```powershell
python -m server319.lsg --cert runs\<run-id>\tls\auth.crt `
    --key runs\<run-id>\tls\auth.key --port 4174 `
    --seconds 180 --log runs\<run-id>\lsg.jsonl
python tools\verify_lsg_capture.py runs\20261020-base
python tools\smoke_lsg_derived.py --run-dir runs\<new-run-id>
```

The default LSG handler validates the entire 28/26/153-byte handshake,
authenticates and decrypts incoming `AB85` frames, and produces `AB85` replies
with a real 8-byte HMAC. Unknown tasks are logged but receive no success
placeholder. Raw LSG frames and reply bytes are retained only in ignored local
`runs/`; review before sharing. The candidate `svc71/task4` reply is based on
a third-party service shape and has only synthetic socket-test coverage so far.

## Capture mode

`python -m server319 --client-dir .\runtime\client-1649370 --port 0 --evidence .\runs\<run-id>\server.jsonl`
starts a 127.0.0.1-only capture listener on a free port after the same
preflight and requires a completed stage receipt. The JSONL evidence log
records a SHA-256 and length, never payload bytes, tickets, passwords, peer
addresses, or arbitrary exception text. No client is launched and no
third-party scripts are imported.
