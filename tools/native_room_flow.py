"""Walk Build 1649370's native lobby into a custom room and toggle the AI row.

Coordinates are client-area pixels for the 1920x1080 client and were measured
from the native lobby screenshots in `runs/natural-c-ui/`.  The flow is split
into named phases so a run can stop at any point and be inspected:

    lobby    开始游戏 tab
    custom   自定义 sub-tab
    create   创建房间 (enters the room scene)
    advanced 高级选项 (two clicks: focus, then open)
    ai       focus the AI开关 row and step it with Right
    apply    应用
    ready    准备
    leave    返回大厅

Example:
    python tools/native_room_flow.py --phases lobby custom create advanced ai
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import click_at
from send_key import press, KEYS


PHASES = {
    "lobby": [("click", 395, 57, 1.5, None)],
    "custom": [("click", 715, 137, 1.5, None)],
    "create": [("click", 1643, 914, 3.0, None)],
    "advanced": [("click", 261, 573, 0.8, None), ("click", 261, 573, 1.5, None)],
    "ai": [("click", 674, 826, 0.8, None),
           ("key", "right", 0, 0, 0.8, "right"),
           ("key", "right", 0, 0, 0.8, "right")],
    "apply": [("click", 1299, 940, 1.5, None)],
    "ready": [("click", 1790, 1050, 3.0, None)],
    "leave": [("click", 1640, 1050, 3.0, None)],
}


def run_phase(hwnd: int, name: str, actions: list, rows: list) -> None:
    for action in actions:
        kind = action[0]
        if kind == "click":
            _, x, y, wait, _ = action
            point = click_at.wt.POINT(x, y)
            if not click_at.user32.ClientToScreen(hwnd, click_at.ctypes.byref(point)):
                raise OSError("ClientToScreen failed")
            click_at.click(point.x, point.y)
            rows.append({"utc": datetime.now(timezone.utc).isoformat(), "phase": name,
                         "action": "click", "client": [x, y], "screen": [point.x, point.y]})
            time.sleep(wait)
        else:
            _, key, _, _, wait, label = action
            press(KEYS[key])
            rows.append({"utc": datetime.now(timezone.utc).isoformat(), "phase": name,
                         "action": "key", "key": key})
            time.sleep(wait)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", default="CODO")
    parser.add_argument("--phases", nargs="+", default=["lobby", "custom", "create", "advanced"])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    hwnd = click_at.user32.FindWindowW(args.window, None)
    if not hwnd:
        raise SystemExit(f"no window of class {args.window}")
    click_at.user32.ShowWindow(hwnd, click_at.SW_RESTORE)
    click_at.user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    rows: list = []
    for phase in args.phases:
        if phase not in PHASES:
            raise SystemExit(f"unknown phase {phase}")
        run_phase(hwnd, phase, PHASES[phase], rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema": 1, "build": 1649370,
                                  "utc": datetime.now(timezone.utc).isoformat(),
                                  "hwnd": hwnd, "phases": args.phases,
                                  "actions": rows}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"evidence": str(output), "actions": len(rows)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
