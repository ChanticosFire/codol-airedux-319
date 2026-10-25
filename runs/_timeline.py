"""Print the forward event timeline with relative offsets from the arm event."""
import json

RAW = r"runs\r300-fwd.json"

raw = open(RAW, encoding="utf-8-sig").read()
obj = json.loads(raw)
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
            extra = a[:46].replace("\n", " ").replace("\r", " ").replace("\x00", ".")
    elif d == "state":
        extra = f"state={e.get('state')} stage={e.get('stage')}"
    ln = e.get("length", "")
    if rel is None:
        print(f"t={t}  {d:6s} len={ln} {extra}")
    else:
        print(f"+{rel:8.3f}s  {d:6s} len={ln} {extra}")
