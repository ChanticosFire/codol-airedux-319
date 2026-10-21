"""Minimal room backend probe for CODOL 1649370: log UDP/TCP traffic on the room port."""
from __future__ import annotations

import argparse
import json
import selectors
import socket
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=28969)
    ap.add_argument("--log", required=True)
    ap.add_argument("--reply", default="", help="optional UTF-8 text reply for every datagram")
    args = ap.parse_args()
    out = Path(args.log)
    out.parent.mkdir(parents=True, exist_ok=True)

    sel = selectors.DefaultSelector()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind(("127.0.0.1", args.port))
    udp.setblocking(False)
    sel.register(udp, selectors.EVENT_READ, "udp")

    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(("127.0.0.1", args.port))
    tcp.listen(8)
    tcp.setblocking(False)
    sel.register(tcp, selectors.EVENT_READ, "tcp")

    def log(row: dict) -> None:
        row["time"] = time.time()
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)

    log({"event": "listening", "port": args.port, "reply": args.reply})
    try:
        while True:
            for key, _ in sel.select(timeout=1.0):
                sock = key.fileobj
                if key.data == "udp":
                    data, addr = sock.recvfrom(65535)
                    log({"event": "udp", "addr": list(addr), "len": len(data), "hex": data.hex(),
                         "text": data.decode("utf-8", "replace")})
                    if args.reply:
                        sock.sendto(args.reply.encode("utf-8"), addr)
                else:
                    conn, addr = sock.accept()
                    conn.setblocking(False)
                    sel.register(conn, selectors.EVENT_READ, "tcp-conn")
                    log({"event": "tcp-accept", "addr": list(addr)})
            for key in list(sel.get_map().values()):
                if key.data != "tcp-conn":
                    continue
                conn = key.fileobj
                try:
                    data = conn.recv(65535)
                except BlockingIOError:
                    continue
                if not data:
                    sel.unregister(conn)
                    conn.close()
                    continue
                log({"event": "tcp", "len": len(data), "hex": data.hex(),
                     "text": data.decode("utf-8", "replace")})
                if args.reply:
                    conn.sendall(args.reply.encode("utf-8"))
    except KeyboardInterrupt:
        pass
    finally:
        for key in list(sel.get_map().values()):
            try:
                key.fileobj.close()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
