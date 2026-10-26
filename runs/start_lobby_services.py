"""Start the three lobby-side services with CORRECT arguments and keep them up.

Round 519's mistake: server319.lsg requires --log (it is not optional) and the
process died immediately on argparse; stderr was discarded so it went unseen.
This script keeps stderr visible and prints each child's pid/returncode on exit.
"""
import os, struct, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"E:\GAME\COD\codol-airedux\319")
STAGE = Path(r"E:\GAME\COD\codol-airedux\1604220")
CLIENT = STAGE/"runtime"/"client-1649370"
TLS = ROOT/"runs"/"20261020-live-derived01"/"tls"
CRT, KEY = str(TLS/"auth.crt"), str(TLS/"auth.key")

rec = bytearray(136); rec[0:4] = bytes([127,0,0,1])
struct.pack_into("<I", rec, 0x80, 2); struct.pack_into("<H", rec, 0x84, 3074)
env = dict(os.environ, LOBBY_UDP_REPLY=bytes(rec).hex(),
           LOBBY_UDP_REPLY_MATCH="1402", LOBBY_UDP_ECHO="0")

specs = [
    ("auth",   [sys.executable,"-m","server319","--auth","--port","4175",
                "--cert",CRT,"--key",KEY,"--client-dir",str(CLIENT),"--seconds","7200"], ROOT, None),
    ("lsg",    [sys.executable,"-m","server319.lsg","--port","4174",
                "--cert",CRT,"--key",KEY,"--log",str(ROOT/"runs"/"live-lsg.jsonl"),
                "--client-dir",str(CLIENT),"--allow-auth-tls","--seconds","7200"], ROOT, None),
    ("lobby",  [sys.executable,"-m","server319.lobby_udp","3074","200",
                str(STAGE/"runs"/"live-lobby.jsonl")], STAGE, env),
]
procs = {}
for name, cmd, cwd, e in specs:
    p = subprocess.Popen(cmd, cwd=str(cwd), env=e)
    procs[name] = p
    print(f"started {name} pid={p.pid}", flush=True)
    time.sleep(2.0)
    if p.poll() is not None:
        print(f"*** {name} EXITED rc={p.returncode} - its stderr above explains why ***", flush=True)
try:
    while True:
        time.sleep(5)
        for name, p in list(procs.items()):
            rc = p.poll()
            if rc is not None:
                print(f"*** {name} died rc={rc} ***", flush=True)
                procs.pop(name)
        if not procs:
            print("all services gone", flush=True)
            break
finally:
    for name, p in procs.items():
        p.terminate()
