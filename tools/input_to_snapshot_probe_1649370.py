"""Ignored diagnostic: turn decoded W packets into authoritative snapshot X."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server1649370.wire164 import _word, build_snapshot
from tools.decode_ps_1649370 import decode_snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', type=Path, required=True)
    ap.add_argument('--snapshot', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--seconds', type=float, default=8)
    args = ap.parse_args()
    base = Path('runs/r738-snapshot-sniprestigea.bin').read_bytes()
    parsed = decode_snapshot(base)
    values = {int(k, 16): v['word'] for k, v in parsed['fields'].items()}
    values[0] = parsed['server_time']

    def frame():
        return build_snapshot(values, server_time=72192, tail_weapon=78,
                              tail_clip_count=30, tail_health=100,
                              entities=((0, 1, {2: _word(200.0)}),),
                              clients=((0, {17: 1, 20: 570, 36: 1}),))

    assert frame() == base
    args.snapshot.write_bytes(base)
    x = 336.0
    movements = []
    errors = []
    with args.log.open('r', encoding='utf8') as log:
        log.seek(0, os.SEEK_END)
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            line = log.readline()
            if not line:
                time.sleep(0.025)
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                errors.append('bad json')
                continue
            if item.get('kind') != 'input_decoded' or item.get('direction') != 1:
                continue
            x = min(400.0, x + 2.0)
            values[0x30] = _word(x)
            tmp = args.snapshot.with_suffix('.tmp')
            tmp.write_bytes(frame())
            os.replace(tmp, args.snapshot)
            movements.append({'seq': item['seq'], 'x': x, 'server_time': item['server_time']})
    args.report.write_text(json.dumps({'movements': movements, 'final_x': x,
                                       'errors': errors}, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'count': len(movements), 'final_x': x, 'errors': errors}))


if __name__ == '__main__':
    main()
