"""One-shot patch: add QUERY1_TYPE switch to the 21/5 reply builder."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "server319" / "lsg_derived.py"
text = path.read_text(encoding="utf-8")
old = '                    body = (_typed_u64(counter) + _typed_u32(0) + b"\\x03" + bytes([task])'
new = (
    '                    q1_type = int(os.environ.get("QUERY1_TYPE", "3")) & 0xFF\n'
    '                    body = (_typed_u64(counter) + _typed_u32(0) + bytes([q1_type])'
    ' + bytes([task])'
)
if old not in text:
    raise SystemExit("pattern not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched")
