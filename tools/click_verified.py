"""Click with verification: repeat until the target region visibly changes.

Simulated clicks occasionally miss in Build 1649370 (window focus, hover states).
This helper captures a region before and after each click and retries until the
region changes or the attempt budget is exhausted, so a flow can prove that a
click actually did something before moving on.

    python tools/click_verified.py --at 310 250 --region 120 220 520 280
    python tools/click_verified.py --at 1445 875 --region 1300 840 1650 920 --repeat 4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


def capture(out: Path, window: str, delay_ms: int = 120) -> Image.Image:
    subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(ROOT / "tools" / "capture_screen.ps1"),
         "-OutFile", str(out), "-WindowClass", window, "-DelayMs", str(delay_ms)],
        check=True, capture_output=True)
    return Image.open(out).convert("RGB")


def region_diff(a: Image.Image, b: Image.Image, box, threshold: int) -> int:
    left, top, right, bottom = box
    crop_a = a.crop((left, top, right, bottom))
    crop_b = b.crop((left, top, right, bottom))
    diff = ImageChops.difference(crop_a, crop_b)
    bbox = diff.getbbox()
    if not bbox:
        return 0
    total = 0
    for pixel in diff.getdata():
        total += sum(pixel)
    return total // max(1, (right - left) * (bottom - top))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", nargs=2, type=int, required=True)
    parser.add_argument("--region", nargs=4, type=int, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--settle", type=float, default=1.2)
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--output")
    args = parser.parse_args()
    tmp = Path(tempfile.gettempdir())
    before_path = tmp / "click_verified_before.png"
    after_path = tmp / "click_verified_after.png"
    row = {"schema": 1, "build": 1649370, "utc": datetime.now(timezone.utc).isoformat(),
           "at": args.at, "region": args.region, "attempts": []}
    before = capture(before_path, args.window)
    changed = False
    for attempt in range(1, args.repeat + 1):
        subprocess.run([sys.executable, str(ROOT / "tools" / "click_at.py"),
                        "--window", args.window, "--at", str(args.at[0]), str(args.at[1])],
                       check=True, capture_output=True)
        time.sleep(args.settle)
        after = capture(after_path, args.window)
        score = region_diff(before, after, args.region, args.threshold)
        changed = score > args.threshold
        row["attempts"].append({"attempt": attempt, "diff": score, "changed": changed})
        before = after
        if changed:
            break
    row["changed"] = changed
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
