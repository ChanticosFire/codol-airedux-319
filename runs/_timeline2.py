"""Print the forward event timeline with relative offsets from the arm event.

The saved stdout came through a PowerShell pipeline, so literal backslash-n
sequences may appear instead of real newlines; normalise before parsing.
"""
import json
import re

RAW = r"runs\r300-fwd.json"

raw = open(RAW, encoding="utf-8-sig").read()
# PowerShell may have escaped newlines as literal \n / \r
if "\\n" in raw and "\n" not in raw.strip()[:20]:
    raw = raw.replace("\\n", "\n").replace("\\r", "\r").replace('\\"', '"')
try:
    obj = json.loads(raw)
except json.JSONDecodeError as exc:
    print(f"parse failed: {exc}")
    print("first 300 chars:", raw[:300].encode("unicode_escape")[:300])
    raise SystemExit(1)

evs = obj.get("events", [])
print(f"sent={obj.get('sent')} received={obj.get('received')} injected={obj.get('injected')}")
print(f"events: {len(evs)}")

t0 = None
for e in evs:
    d = e.get("dir", "?")
    t = e.get("t")
    if d == "arm":
        t0 = t
        st = (e.get("result") or {}).get("state")
        print(f"t={t}  arm  state={st}   <-- baseline")
        continue
    if t0 is None:
        t0 = t
    rel = (t - t0) if isinstance(t, (int, float)) else None
    extra = ""
    if d in ("out", "in"):
        a = e.get("ascii") or ""
        if a:
            extra = re.sub(r"[\x00-\x1f]", ".", a)[:46]
    elif d == "state":
        extra = f"state={e.get('state')} stage={e.get('stage')}"
    ln = e.get("length", "")
    if rel is None:
        print(f"t={t}  {d:6s} len={ln} {extra}")
    else:
        print(f"+{rel:8.3f}s  {d:6s} len={ln} {extra}")
