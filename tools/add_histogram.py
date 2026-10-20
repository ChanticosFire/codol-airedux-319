"""Add a --histogram option to probe_reg.py without inline-quoting headaches.

Round 123 needs the distribution of the count slot, not just its changes: whether the
positive readings dominate decides which half of the contradiction is real.
"""
from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parent / "probe_reg.py"


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if "--histogram" in text:
        print("already patched")
        return

    text = text.replace(
        '    ap.add_argument("--label", default="")',
        '    ap.add_argument("--label", default="")\n'
        '    ap.add_argument("--histogram", action="store_true",\n'
        '                    help="tally every sampled value of the first mem-ebp slot")',
    )
    text = text.replace(
        "        deadline = time.time() + args.secs\n"
        "        last_n = 0\n"
        "        last_v = None",
        "        deadline = time.time() + args.secs\n"
        "        last_n = 0\n"
        "        last_v = None\n"
        "        hist: dict[int, int] = {}",
    )
    text = text.replace(
        '            v = struct.unpack_from("<I", raw_v, 0)[0]',
        '            v = struct.unpack_from("<I", raw_v, 0)[0]\n'
        "            if args.histogram and ebp_offs:\n"
        '                h0 = struct.unpack_from("<I", raw_v, 4)[0]\n'
        "                hist[h0] = hist.get(h0, 0) + 1",
    )
    text = text.replace(
        "        if last_v is None:",
        "        if args.histogram and hist:\n"
        "            total = sum(hist.values())\n"
        "            pos = sum(c for val, c in hist.items() if 0 < val < 0x80000000)\n"
        "            neg = sum(c for val, c in hist.items() if val >= 0x80000000)\n"
        "            zero = hist.get(0, 0)\n"
        '            print(f"[{label}] HISTOGRAM over {total} samples: "'
        'f"positive={pos} ({100*pos/total:.1f}%) zero={zero} "'
        'f"negative={neg} ({100*neg/total:.1f}%)")\n'
        "            for val, c in sorted(hist.items(), key=lambda kv: -kv[1])[:8]:\n"
        '                print(f"    {val:#010x}  x{c}")\n'
        "        if last_v is None:",
    )
    PATH.write_text(text, encoding="utf-8")
    print("histogram patched")


if __name__ == "__main__":
    main()
