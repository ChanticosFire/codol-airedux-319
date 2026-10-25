"""Extract forward event timestamps with regex (the saved stdout is not valid JSON
because the PowerShell pipeline flattened newlines into literal backslash-n)."""
import re

RAW = r"runs\r300-fwd.json"

raw = open(RAW, encoding="utf-8-sig").read()

# Each event object starts with {"t": <num>, "dir": "<name>"
pat = re.compile(r'"t":\s*([0-9.]+),\s*"dir":\s*"([a-z_]+)"')
rows = [(float(m.group(1)), m.group(2)) for m in pat.finditer(raw)]
print(f"events parsed: {len(rows)}")

# arm carries a hard-coded t=0.0; the rest are absolute monotonic values.
abs_rows = [(t, d) for t, d in rows if t > 0.0]
base = abs_rows[0][0] if abs_rows else 0.0
print(f"first absolute t = {base:.3f}  (arm uses the sentinel 0.0)")
print()
for t, d in abs_rows:
    print(f"+{t - base:8.3f}s  {d}")

# also pull the ascii payloads to see which packet is which
print()
print("=== packets (first 8) ===")
pat2 = re.compile(r'"length":\s*(\d+),[^}]*?"ascii":\s*"((?:[^"\\]|\\.)*)"', re.S)
shown = 0
for m in pat2.finditer(raw):
    length = m.group(1)
    txt = m.group(2)
    txt = txt.replace("\\u0000", ".").replace("\\n", " ").replace("\\r", " ")
    txt = re.sub(r"\\x[0-9a-fA-F]{2}", "?", txt)
    print(f"  len={length:>5s}  {txt[:52]}")
    shown += 1
    if shown >= 8:
        break
