"""Locate the in-game mouse cursor inside a game screenshot.

The lobby draws its own cursor (a 45x38 arrow), so a screenshot shows exactly
where the client believes the pointer is.  Template matching against
`tools/cursor_template.png` reports that position, which lets us measure the
gap between a requested click coordinate and the real one.

    python tools/find_cursor.py --image runs/natural-bl-ui/after-create2.png
    python tools/find_cursor.py --capture --window CODO
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Run me with the bundled interpreter that ships numpy:
#   & "C:\\Users\\Administrator\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe" tools/find_cursor.py ...
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tools" / "cursor_template.png"


def load_gray(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float64)


def match(image: np.ndarray, template: np.ndarray) -> tuple[int, int, float]:
    """Exhaustive SSD template match via FFT correlation."""
    ih, iw = image.shape
    th, tw = template.shape
    if th > ih or tw > iw:
        raise ValueError("template larger than image")
    size = (1 << int(np.ceil(np.log2(ih + th))), 1 << int(np.ceil(np.log2(iw + tw))))
    corr = np.fft.irfft2(np.fft.rfft2(image, size) * np.conj(np.fft.rfft2(template, size)))
    corr = corr[: ih - th + 1, : iw - tw + 1]
    ones = np.ones(template.shape)
    sq = np.fft.irfft2(np.fft.rfft2(image * image, size) * np.conj(np.fft.rfft2(ones, size)))
    sq = sq[: ih - th + 1, : iw - tw + 1]
    ssd = sq + float((template * template).sum()) - 2.0 * corr
    index = int(np.argmin(ssd))
    y, x = divmod(index, iw - tw + 1)
    return x, y, float(ssd[y, x])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--hotspot", nargs=2, type=int, default=[10, 10],
                        help="arrow tip offset inside the template")
    parser.add_argument("--output")
    args = parser.parse_args()
    row = {"schema": 1, "build": 1649370, "utc": datetime.now(timezone.utc).isoformat()}
    if args.capture:
        tmp = Path(tempfile.gettempdir()) / "find_cursor.png"
        subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(ROOT / "tools" / "capture_screen.ps1"),
             "-OutFile", str(tmp), "-WindowClass", args.window, "-DelayMs", "120"],
            check=True, capture_output=True)
        image_path = tmp
    elif args.image:
        image_path = Path(args.image)
    else:
        parser.error("give --image or --capture")
    image = load_gray(image_path)
    template = load_gray(TEMPLATE)
    x, y, score = match(image, template)
    row.update({"image": str(image_path), "template": str(TEMPLATE),
                "cursor_top_left": [x, y],
                "hotspot": [x + args.hotspot[0], y + args.hotspot[1]],
                "score": score,
                "image_size": [image.shape[1], image.shape[0]]})
    text = json.dumps(row, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
