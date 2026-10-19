"""CLI for the passive Build 1649370 research service."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .manifest import BUILD, verify_client
from .service import EvidenceLog, LoopbackServer


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 1649370 loopback research service")
    parser.add_argument("--client-dir", type=Path, required=True,
                        help="unmodified Build 1649370 client directory")
    parser.add_argument("--preflight", action="store_true",
                        help="verify the client and exit without opening a listener")
    parser.add_argument("--port", type=int, default=0,
                        help="loopback TCP port; default 0 selects an unused port")
    parser.add_argument("--evidence", type=Path, default=Path("server319-evidence.jsonl"),
                        help="metadata-only JSONL log path; no raw frames or secrets")
    parser.add_argument("--auth", action="store_true",
                        help="serve the observed HTTP/TLS /auth/ endpoint instead of the capture listener")
    parser.add_argument("--cert", type=Path, help="lab TLS certificate (PEM) for --auth")
    parser.add_argument("--key", type=Path, help="lab TLS private key (PEM) for --auth")
    parser.add_argument("--seconds", type=float, default=180.0,
                        help="how long the --auth listener stays up")
    args = parser.parse_args()

    try:
        checks = verify_client(args.client_dir)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"preflight error: {exc}\n")
    print(json.dumps({"build": BUILD, "checks": [asdict(c) for c in checks]},
                     indent=2))
    if not all(c.ok for c in checks):
        return 2
    if args.preflight:
        return 0
    workspace = Path(__file__).resolve().parents[1]
    staged = workspace / "runtime" / "client-1649370"
    receipt_path = staged.parent / "client-1649370.stage-receipt.json"
    if args.client_dir.resolve() != staged.resolve() or not receipt_path.is_file():
        parser.exit(2, "listener requires the verified isolated client stage\n")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "verified" or receipt.get("destination") != str(staged):
        parser.exit(2, "isolated client stage receipt is incomplete\n")
    evidence = args.evidence.resolve()
    run_root = workspace / "runs"
    if run_root not in evidence.parents:
        parser.exit(2, "evidence path must be inside 319/runs\n")
    if args.auth:
        from .auth import AuthEvidence, AuthServer
        if not args.cert or not args.key:
            parser.exit(2, "--auth requires --cert and --key\n")
        port = args.port or 4175
        server = AuthServer(port, args.cert, args.key, AuthEvidence(evidence))
        server.start()
        print(f"Auth listening on 127.0.0.1:{port} for {args.seconds:g}s", flush=True)
        try:
            server.serve(args.seconds)
        except KeyboardInterrupt:
            pass
        finally:
            server.close()
        return 0
    with LoopbackServer(args.port, EvidenceLog(evidence)) as server:
        print(f"Listening on 127.0.0.1:{server.server_address[1]} (capture only)", flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
