# Build 1649370 server research scaffold

This is an independent, passive local service. It verifies four known Build
1649370 client files before opening a listener. It accepts a provisional
little-endian 32-bit length envelope and records metadata for unknown frames.
It has **no Auth, LSG, room, match, or gameplay reply implementation**. A
received frame never produces a fabricated success response.

Run from `319`:

```powershell
python -m server319 --help
python -m server319 --client-dir 'E:\GAME\COD\使命召唤OL' --preflight
python -m unittest server319.test_server319
```

`python -m server319 --client-dir .\runtime\client-1649370 --port 0 --evidence .\runs\<run-id>\server.jsonl` starts a
127.0.0.1-only capture listener on a free port after the same preflight and
requires a completed stage receipt. The
JSONL evidence log records a SHA-256 and length, never payload bytes, tickets,
passwords, peer addresses, or arbitrary exception text. No client is launched
and no third-party scripts are imported. This transport candidate still needs
verification against Build 1649370 traffic before protocol work proceeds.
