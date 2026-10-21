"""Read-only, bounded string leads from the verified Build 1649370 codo.gfx copy.

String adjacency is only a lead for ABC method tracing; it is not a call graph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MOVIE_SIZE = 7664688
MOVIE_SHA256 = "314c4abd6936b02955e2f31f781b20ac119ea9878f83698d1a1d6f106558c31c"
TERMS = (
    "codo.controllers:LobbyController/private:onChangeReadyStateHandle",
    "codo.controllers:LobbyController/private:isReady",
    "cppSetMemberReadyState",
    "SetReadyState",
    "StartMatch",
    "StartMatchCountDown",
)


def scan(movie: bytes) -> dict:
    if len(movie) != MOVIE_SIZE or hashlib.sha256(movie).hexdigest() != MOVIE_SHA256:
        raise ValueError("codo.gfx does not match the verified Build 1649370 source")
    found = {}
    for term in TERMS:
        needle = term.encode("ascii")
        offsets = []
        start = 0
        while (offset := movie.find(needle, start)) >= 0:
            offsets.append(hex(offset))
            start = offset + 1
        found[term] = offsets
    return {"schema": 1, "movie_size": len(movie), "movie_sha256": MOVIE_SHA256,
            "method": "exact ASCII byte-string search in the verified original GFX; no ABC control-flow decoding",
            "offsets": found,
            "interpretation_limit": "String proximity suggests candidates only; calls, direction and UI event execution remain unverified."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("movie", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = scan(args.movie.read_bytes())
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
