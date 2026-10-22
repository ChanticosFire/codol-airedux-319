"""Probe the community client's native TCP conn against a loopback listener.

Only allocates memory and invokes existing functions in the running client copy.
The listener is confined to 127.0.0.1 and closes when the probe finishes.
"""
from __future__ import annotations

import ctypes as C
import argparse
import hashlib
import json
import socket
import struct
import threading
import time
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

import start_conn as sc

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(r"E:\GAME\COD\1649370\bin\v1649370\codol1649370-offline.exe")
PORT = 28969


def invoke(handle: int, code: bytes) -> dict:
    cave = int(sc.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    if not cave:
        raise OSError("VirtualAllocEx failed")
    sc.w(handle, cave, code(cave) if callable(code) else code)
    tid = W.DWORD()
    thread = sc.k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
    if not thread:
        raise OSError("CreateRemoteThread failed")
    wait = sc.k32.WaitForSingleObject(thread, 5000)
    exit_code = W.DWORD()
    sc.k32.GetExitCodeThread(thread, C.byref(exit_code))
    sc.k32.CloseHandle(thread)
    if wait == 0:
        sc.k32.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
        sc.k32.VirtualFreeEx(handle, C.c_void_p(cave), 0, 0x8000)
    return {"cave": hex(cave), "thread_id": tid.value, "wait": wait,
            "return": hex(exit_code.value)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-server", action="store_true",
                        help="Use an already running 127.0.0.1:28969 LSG server")
    parser.add_argument("--pump-seconds", type=float, default=0)
    parser.add_argument("--recv-pump", action="store_true",
                        help="Drive native BA41D0 receive state machine after connect tick")
    parser.add_argument("--outer-pump", action="store_true",
                        help="Drive native BA4430 receive and gate dispatch")
    parser.add_argument("--netobj-pump", action="store_true",
                        help="Drive native B838A0 owner pump and event dispatch")
    args = parser.parse_args()
    result: dict = {"schema": 1, "build": 1649370,
                    "utc": datetime.now(timezone.utc).isoformat(),
                    "exe": str(EXE), "exe_sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
                    "listener": f"127.0.0.1:{PORT}", "patches": []}
    listener = None
    accepted: dict = {}
    connected = threading.Event()
    release = threading.Event()

    def accept_one() -> None:
        try:
            peer, address = listener.accept()
            accepted["peer"] = list(address)
            connected.set()
            release.wait(timeout=15)
            peer.settimeout(1)
            try:
                payload = peer.recv(512)
                accepted["first_bytes_hex"] = payload.hex()
            except socket.timeout:
                accepted["first_bytes_hex"] = ""
            finally:
                peer.close()
        except OSError as error:
            accepted["error"] = repr(error)

    worker = None
    if not args.external_server:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", PORT))
        listener.listen(1)
        listener.settimeout(25)
        worker = threading.Thread(target=accept_one, daemon=True)
        worker.start()
    handle = None
    try:
        pid = sc.find_pid()
        result["pid"] = pid
        handle = sc.k32.OpenProcess(0x1F0FFF, False, pid)
        if not handle:
            raise OSError("OpenProcess failed")
        netobj = sc.u32(handle, 0x8269774)
        if not netobj:
            result["init_netobj"] = invoke(handle, lambda cave:
                b"\xe8" + struct.pack("<i", 0x803830 - (cave + 5)) + b"\xc3")
            netobj = sc.u32(handle, 0x8269774)
        result["netobj"] = hex(netobj)
        if not netobj:
            raise RuntimeError("netobj was not initialized")
        cfg = int(sc.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x04))
        if not cfg:
            raise OSError("VirtualAllocEx config failed")
        config = bytearray(0x88)
        struct.pack_into("<II", config, 0, 4, 0x0100007F)
        # B75440 reads [address+0x84]; C76920 then calls htons.
        struct.pack_into("<H", config, 0x84, PORT)
        sc.w(handle, cfg, bytes(config))
        address = int(sc.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x04))
        if not address:
            raise OSError("VirtualAllocEx address failed")
        tcp_address = bytearray(0x88)
        # C76920 reads the first dword of this by-value block directly as
        # sin_addr; unlike the other config, there is no leading type field.
        struct.pack_into("<I", tcp_address, 0, 0x0100007F)
        struct.pack_into("<H", tcp_address, 0x84, PORT)
        sc.w(handle, address, bytes(tcp_address))
        result["config"] = {"remote": hex(cfg), "ip_hex": config[4:8].hex(),
                            "port_offset": "0x84", "port_host_order": PORT,
                            "port_bytes_hex": config[0x84:0x86].hex(),
                            "tcp_address_remote": hex(address),
                            "tcp_address_ip_hex": tcp_address[:4].hex()}

        def connect_code(cave: int) -> bytes:
            code = bytearray()
            code += b"\x6a\x00" + b"\x68" + struct.pack("<I", cfg)
            code += b"\x81\xec\x88\x00\x00\x00"
            # B82070 takes this 0x88 block by value. Its constructor copies
            # the block to conn+8; BA4080 later passes conn+8 to C73900.
            code += b"\xbe" + struct.pack("<I", address)
            code += b"\x89\xe7\xb9\x22\x00\x00\x00\xf3\xa5"
            code += b"\xb9" + struct.pack("<I", netobj)
            call_pos = len(code)
            code += b"\xe8\x00\x00\x00\x00\xc3"
            struct.pack_into("<i", code, call_pos + 1,
                             0xB82070 - (cave + call_pos + 5))
            return bytes(code)

        result["native_connect"] = invoke(handle, connect_code)
        connected.wait(timeout=3)
        conn = sc.u32(handle, netobj + 0x4F4)
        result["conn"] = hex(conn)
        if conn:
            outer_context = 0
            if args.outer_pump:
                outer_context = int(sc.k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x04))
                if not outer_context:
                    raise OSError("VirtualAllocEx outer context failed")
                result["outer_context"] = {"state_out": hex(outer_context),
                                           "crypto_holder": hex(outer_context + 0x10)}
            result["conn_state"] = {"socket": hex(sc.u32(handle, conn + 0xC4)),
                                    "c8": sc.u32(handle, conn + 0xC8),
                                    "constructor_type": sc.u32(handle, conn + 8),
                                    "constructor_ip_hex": struct.pack(
                                        "<I", sc.u32(handle, conn + 12)).hex(),
                                    "constructor_port_bytes_hex": struct.pack(
                                        "<I", sc.u32(handle, conn + 8 + 0x84))[:2].hex(),
                                    "copied_port_bytes_hex": struct.pack(
                                        "<I", sc.u32(handle, conn + 0x538 + 0x84))[:2].hex()}
            result["tick"] = invoke(handle, lambda cave:
                b"\xb9" + struct.pack("<I", conn) + b"\xe8" +
                struct.pack("<i", 0xBA24C0 - (cave + 10)) + b"\xc3")
            result["conn_state_after_tick"] = {
                "socket": hex(sc.u32(handle, conn + 0xC4)),
                "c8": sc.u32(handle, conn + 0xC8),
                "c0": sc.u32(handle, conn + 0xC0),
                "b8": sc.u32(handle, conn + 0xB8),
                "9c": sc.u32(handle, conn + 0x9C),
                "a4": sc.u32(handle, conn + 0xA4),
                "ac": sc.u32(handle, conn + 0xAC),
                "5e8": sc.u32(handle, conn + 0x5E8),
                "640": sc.u32(handle, conn + 0x640),
                "644": sc.u32(handle, conn + 0x644)}
            if args.pump_seconds > 0:
                deadline = time.monotonic() + args.pump_seconds
                samples = []
                while time.monotonic() < deadline:
                    time.sleep(0.25)
                    target = (0xB838A0 if args.netobj_pump else
                              0xBA4430 if args.outer_pump else
                              0xBA41D0 if args.recv_pump else 0xBA24C0)
                    def tick_code(cave: int) -> bytes:
                        code = bytearray()
                        if args.outer_pump:
                            code += b"\x68" + struct.pack("<I", outer_context + 0x10)
                            code += b"\x68" + struct.pack("<I", outer_context)
                        code += b"\xb9" + struct.pack("<I", netobj if args.netobj_pump else conn)
                        call_at = len(code)
                        code += b"\xe8\x00\x00\x00\x00\xc3"
                        struct.pack_into("<i", code, call_at + 1,
                                         target - (cave + call_at + 5))
                        return bytes(code)
                    tick = invoke(handle, tick_code)
                    samples.append({"elapsed_ms": round((args.pump_seconds - max(0, deadline - time.monotonic())) * 1000),
                                    "tick": tick, "c8": sc.u32(handle, conn + 0xC8),
                                    "c0": sc.u32(handle, conn + 0xC0),
                                    "b8": sc.u32(handle, conn + 0xB8),
                                    "9c": sc.u32(handle, conn + 0x9C),
                                    "a4": sc.u32(handle, conn + 0xA4),
                                    "ac": sc.u32(handle, conn + 0xAC),
                                    "5e8": sc.u32(handle, conn + 0x5E8),
                                    "640": sc.u32(handle, conn + 0x640),
                                    "644": sc.u32(handle, conn + 0x644)})
                    if args.outer_pump:
                        samples[-1]["state_out"] = sc.u32(handle, outer_context)
                        samples[-1]["crypto_holder"] = hex(sc.u32(handle, outer_context + 0x10))
                    if args.netobj_pump:
                        samples[-1]["owner"] = hex(sc.u32(handle, netobj + 4))
                        samples[-1]["owner_event"] = sc.u32(handle, netobj + 0x5B8)
                        samples[-1]["global_state"] = sc.u32(handle, 0x84ABA7C)
                    if len(samples) >= 200:
                        break
                result["pump_samples"] = samples
        release.set()
        if worker:
            worker.join(timeout=10)
            result["accepted"] = accepted
    finally:
        release.set()
        if listener:
            listener.close()
        if handle:
            sc.k32.CloseHandle(handle)
        name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output = ROOT / "evidence" / "experiments" / f"{name}-1649370-native-tcp.json"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"evidence": str(output), **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
