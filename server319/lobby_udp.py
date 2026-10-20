"""Loopback lobby endpoint on 3074 (UDP + TCP), as the community report requires.

From the 2026-10-20 community note:

    the handshake goes over UDP, not TCP. 0xbb1420 is the sendto wrapper; it
    builds "1E" + u16([session+0x12C]) and sends it to 127.0.0.1:3074. So the
    client needs a TCP+UDP listener on 3074 and the handshake packet is echoed
    back unchanged. The repeated [111] was most likely because nothing answered
    on UDP 3074.

This module only binds loopback and echoes; it never talks to the internet and
does not change any host networking configuration.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path


class LobbyEndpoint:
    """UDP echo plus a quiet TCP listener on the same loopback port."""

    def __init__(self, port: int = 3074, log_path: Path | None = None,
                 echo: bool = True) -> None:
        self.port = port
        self.echo = echo
        self.log_path = log_path
        self._stop = threading.Event()
        self._udp: socket.socket | None = None
        self._tcp: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def note(self, event: str, **fields) -> None:
        row = {"event": event, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "utc_local": time.strftime("%H:%M:%S"), **fields}
        line = json.dumps(row, ensure_ascii=False)
        print(line, flush=True)
        if self.log_path is not None:
            try:
                with self._lock, self.log_path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError:
                pass

    def start(self) -> None:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.bind(("127.0.0.1", self.port))
        udp.settimeout(0.5)
        self._udp = udp

        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind(("127.0.0.1", self.port))
        tcp.listen(8)
        tcp.settimeout(0.5)
        self._tcp = tcp

        self._threads = [
            threading.Thread(target=self._udp_loop, daemon=True),
            threading.Thread(target=self._tcp_loop, daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self.note("endpoint_up", port=self.port, echo=self.echo)

    def _udp_loop(self) -> None:
        assert self._udp is not None
        while not self._stop.is_set():
            try:
                data, addr = self._udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            self.note("udp_in", src=f"{addr[0]}:{addr[1]}", length=len(data),
                      hex=data.hex())
            if self.echo:
                try:
                    self._udp.sendto(data, addr)
                    self.note("udp_echo", length=len(data))
                except OSError as exc:
                    self.note("udp_echo_failed", error=type(exc).__name__)

    def _tcp_loop(self) -> None:
        assert self._tcp is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._tcp.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._tcp_conn, args=(conn, addr), daemon=True).start()

    def _tcp_conn(self, conn: socket.socket, addr) -> None:
        peer = f"{addr[0]}:{addr[1]}"
        self.note("tcp_in", src=peer)
        conn.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                self.note("tcp_data", src=peer, length=len(data), hex=data.hex()[:200])
                if self.echo:
                    conn.sendall(data)
                    self.note("tcp_echo", src=peer, length=len(data))
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            self.note("tcp_closed", src=peer)

    def stop(self) -> None:
        self._stop.set()
        for sock in (self._udp, self._tcp):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        for thread in self._threads:
            thread.join(timeout=2.0)
        self.note("endpoint_down")


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3074
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    log = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    server = LobbyEndpoint(port, log)
    server.start()
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
