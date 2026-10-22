"""Loopback ring bridge for Build 1649370 (static-verified, tool only).

Evidence basis (all from the exact offline image, see
`tools/disasm_image_1649370.py` dumps recorded in this round's JSON):

* `0x675140` reads the inbound loopback ring B:
  slot = 0x786DBC0 + (read & 0xF) * 0x504, adr at slot+0, payload at
  slot+0x18, length at slot+0x500; cursors 0x7872C00/0x7872C04.
* `0x4F8D70` is the client receive pump; it drains ring B and hands each
  packet to `0x5C2260` (CL packet event) which dispatches OOB strings
  (`0xFFFFFFFF` prefix) to `0x5C1EE0`.
* `0x6750A0`/`0x5BAA00` write NA_LOOPBACK (type 2) packets into the local
  server queue ring C: 0x7867768 + port * 0x62C8, 20 slots of 0x4F0,
  cursors at +0x62C0/+0x62C4, length at +0x4E8, port at +0x4EC.
* `0x675390(ecx=string, esi=adr_out)` maps "localhost" to a type 2 adr with
  port 0 and channel 0x9D.
* `0x5BE730` is the client's natural connect entry: it sets the connection
  phase, parses `[0xC7AF590]`, writes the adr into the connection and calls
  the `0x5C05F0` state machine which sends `getchallenge`.

The tool never patches game code. For calls that must run on the window
thread it suspends the CODO window thread, redirects EIP into a small
`pushad; ...; call; popad; ret` cave and resumes it (the same primitive as
`tools/call_main_thread.py`, extended with several calls per invocation).

Subcommands:

    python tools/ring_bridge_1649370.py status
    python tools/ring_bridge_1649370.py connect --address localhost
    python tools/ring_bridge_1649370.py drain-ring-c --port 0
    python tools/ring_bridge_1649370.py inject-oob --text "challengeResponse 1"
    python tools/ring_bridge_1649370.py pump
    python tools/ring_bridge_1649370.py forward --target 127.0.0.1:28969 --seconds 60
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import socket
import struct
import subprocess
import time
from ctypes import wintypes as W
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE_NAME = "codol1649370-offline.exe"

k32 = C.WinDLL("kernel32", use_last_error=True)
user32 = C.WinDLL("user32", use_last_error=True)

k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
k32.OpenThread.restype = W.HANDLE
k32.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.SuspendThread.argtypes = [W.HANDLE]
k32.SuspendThread.restype = W.DWORD
k32.ResumeThread.argtypes = [W.HANDLE]
k32.ResumeThread.restype = W.DWORD
user32.FindWindowW.restype = W.HWND
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.GetWindowThreadProcessId.restype = W.DWORD

PROCESS_ALL = 0x1F0FFF
CONTEXT_SIZE = 716
EIP_OFFSET = 184
ESP_OFFSET = 196
CONTEXT_FLAGS = 0x00010003  # CONTEXT_i386 | CONTROL | INTEGER

STATE = 0x76446B0
CONNECTION_ENCODED = 0x331C0C8
CONNECTION_XOR = 0xD362501F
ADDRESS_STRING = 0xC7AF590
STAGE = 0xE59D20

RING_B_BASE = 0x786DBC0
RING_B_STRIDE = 0x504
RING_B_SLOTS = 16
RING_B_READ = 0x7872C00
RING_B_WRITE = 0x7872C04
RING_B_PAYLOAD = 0x18
RING_B_LENGTH = 0x500

RING_C_BASE = 0x7867768
RING_C_STRIDE = 0x62C8
RING_C_SLOTS = 20
RING_C_SLOT_STRIDE = 0x4F0
RING_C_LENGTH = 0x4E8
RING_C_PORT = 0x4EC

# Outgoing client->local-server packets for client slot 0 (the branch of
# 0x6750A0 taken when the connection index is 0 / NA_LOOPBACK).
RING_A_BASE = 0x7872C08
RING_A_STRIDE = 0x4F0
RING_A_SLOTS = 64
RING_A_READ = 0x7886808
RING_A_WRITE = 0x788680C
RING_A_LENGTH = 0x4E8
RING_A_TYPE = 0x4EC

CONNECT_FN = 0x5BE730
PUMP_FN = 0x4F8D70
RING_A_DRAIN_FN = 0x674F30
RING_A_DRAIN_ORIGINAL = bytes.fromhex("558bec")
HEARTBEAT_FN = 0x5B3160
HEARTBEAT_ORIGINAL = bytes.fromhex("558bec")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_pid() -> int:
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV"],
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    raise SystemExit(f"{EXE_NAME} 未运行")


class Client:
    def __init__(self) -> None:
        self.pid = find_pid()
        self.handle = k32.OpenProcess(PROCESS_ALL, False, self.pid)
        if not self.handle:
            raise SystemExit(f"OpenProcess 失败: {C.get_last_error()}")

    def close(self) -> None:
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = 0

    def read(self, va: int, size: int) -> bytes | None:
        buf = C.create_string_buffer(size)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(self.handle, C.c_void_p(va), buf, size, C.byref(got)) or got.value != size:
            return None
        return buf.raw

    def write(self, va: int, blob: bytes) -> bool:
        got = C.c_size_t()
        ok = k32.WriteProcessMemory(self.handle, C.c_void_p(va),
                                    C.create_string_buffer(blob, len(blob)), len(blob), C.byref(got))
        return bool(ok) and got.value == len(blob)

    def u32(self, va: int) -> int:
        blob = self.read(va, 4)
        return struct.unpack("<I", blob)[0] if blob else 0

    def w32(self, va: int, value: int) -> bool:
        return self.write(va, struct.pack("<I", value))

    def connection(self) -> int:
        return self.u32(CONNECTION_ENCODED) ^ CONNECTION_XOR

    def status(self) -> dict:
        connection = self.connection()
        row = {
            "utc": now(),
            "pid": self.pid,
            "stage": self.u32(STAGE),
            "state": self.u32(STATE),
            "connection": hex(connection),
            "ring_b": {"read": self.u32(RING_B_READ), "write": self.u32(RING_B_WRITE)},
            "ring_a": {"read": self.u32(RING_A_READ), "write": self.u32(RING_A_WRITE)},
            "ring_c0": {
                "read": self.u32(RING_C_BASE + RING_C_SLOTS * RING_C_SLOT_STRIDE + 0),
                "write": self.u32(RING_C_BASE + 0x62C4),
            },
            "address_string": (self.read(ADDRESS_STRING, 64) or b"").split(b"\0")[0].decode("latin-1"),
        }
        if 0x10000 <= connection < 0x7FFF0000:
            adr = self.read(connection + 0x14, 0x18)
            if adr:
                adr_type, ip, port = struct.unpack_from("<I4sH", adr)
                row["connection_adr"] = {
                    "type": adr_type,
                    "ip": socket.inet_ntoa(ip),
                    "port": socket.ntohs(port),
                    "channel": struct.unpack_from("<I", adr, 0x14)[0],
                }
            row["connection_state"] = self.u32(connection + 0x100260)
        return row

    # ---- window-thread invocation -------------------------------------
    def _thread_id(self, window: str) -> int:
        hwnd = user32.FindWindowW(window, None)
        if not hwnd:
            raise SystemExit(f"找不到窗口类 {window}")
        return user32.GetWindowThreadProcessId(hwnd, None)

    def invoke_sequence(self, calls: list[dict], window: str = "CODO", settle: float = 1.5,
                        timeout: float = 20.0) -> dict:
        """Suspend the window thread once and run each call in order.

        Each call: {"target": int, "args": [int...], "eax": int|None, "ecx": int|None}
        The cave restores all registers before returning to the original EIP.
        """
        tid = self._thread_id(window)
        thread = k32.OpenThread(0x1F03FF, False, tid)
        if not thread:
            raise SystemExit(f"OpenThread 失败: {C.get_last_error()}")
        row: dict = {"utc": now(), "pid": self.pid, "tid": tid, "calls": []}
        suspended = False
        resumed = False
        try:
            if k32.SuspendThread(thread) == 0xFFFFFFFF:
                raise SystemExit(f"SuspendThread 失败: {C.get_last_error()}")
            suspended = True
            storage = C.create_string_buffer(CONTEXT_SIZE + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, CONTEXT_SIZE)
            C.c_uint32.from_address(aligned).value = CONTEXT_FLAGS
            wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
            wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
            wow64_get.argtypes = [W.HANDLE, C.c_void_p]
            wow64_set.argtypes = [W.HANDLE, C.c_void_p]
            if not wow64_get(thread, C.c_void_p(aligned)):
                raise SystemExit(f"GetThreadContext 失败: {C.get_last_error()}")
            original_eip = C.c_uint32.from_address(aligned + EIP_OFFSET).value
            original_esp = C.c_uint32.from_address(aligned + ESP_OFFSET).value
            row["original"] = {"eip": hex(original_eip), "esp": hex(original_esp)}

            cave = int(k32.VirtualAllocEx(self.handle, None, 0x1000, 0x3000, 0x40))
            if not cave:
                raise SystemExit("VirtualAllocEx 失败")
            row["cave"] = hex(cave)
            code = bytearray(b"\x60")  # pushad
            offsets = []
            for call in calls:
                if call.get("eax") is not None:
                    code += b"\xb8" + struct.pack("<I", call["eax"] & 0xFFFFFFFF)
                if call.get("ecx") is not None:
                    code += b"\xb9" + struct.pack("<I", call["ecx"] & 0xFFFFFFFF)
                for value in reversed(call.get("args", [])):
                    code += b"\x68" + struct.pack("<I", value & 0xFFFFFFFF)
                offsets.append(len(code))
                code += b"\xe8\x00\x00\x00\x00"  # call target (patched below)
            code += b"\x61\xc3"  # popad; ret
            for call, offset in zip(calls, offsets):
                struct.pack_into("<I", code, offset + 1,
                                 (call["target"] - (cave + offset + 5)) & 0xFFFFFFFF)
            self.write(cave, bytes(code))
            k32.FlushInstructionCache(self.handle, C.c_void_p(cave), len(code))

            return_slot = original_esp - 4
            self.write(return_slot, struct.pack("<I", original_eip))
            C.c_uint32.from_address(aligned + ESP_OFFSET).value = return_slot
            C.c_uint32.from_address(aligned + EIP_OFFSET).value = cave
            if not wow64_set(thread, C.c_void_p(aligned)):
                raise SystemExit(f"SetThreadContext 失败: {C.get_last_error()}")
            k32.ResumeThread(thread)
            resumed = True
            row["resumed"] = True
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.25)
                if k32.SuspendThread(thread) != 0xFFFFFFFF:
                    # Still executing our cave?  Check EIP against the cave range.
                    probe = C.create_string_buffer(CONTEXT_SIZE + 16)
                    p = (C.addressof(probe) + 15) & ~15
                    C.memset(p, 0, CONTEXT_SIZE)
                    C.c_uint32.from_address(p).value = CONTEXT_FLAGS
                    if wow64_get(thread, C.c_void_p(p)):
                        eip = C.c_uint32.from_address(p + EIP_OFFSET).value
                        k32.ResumeThread(thread)
                        if not (cave <= eip < cave + len(code)):
                            row["returned_eip"] = hex(eip)
                            break
                    else:
                        k32.ResumeThread(thread)
                        break
            else:
                row["returned_eip"] = "timeout"
            row["process_alive_after"] = bool(k32.OpenProcess(0x1000, False, self.pid))
        finally:
            if suspended and not resumed:
                try:
                    k32.ResumeThread(thread)
                    row["resumed_in_cleanup"] = True
                except Exception:
                    pass
            try:
                k32.CloseHandle(thread)
            except Exception:
                pass
            row["finished"] = now()
        return row

    # ---- ring helpers -------------------------------------------------
    def inject_oob(self, text: str, adr_type: int = 2, port: int = 0) -> dict:
        payload = b"\xff\xff\xff\xff" + text.encode("latin-1") + b"\0"
        adr = struct.pack("<I4sHHIII", adr_type, b"\0\0\0\0", socket.htons(port), 0, 0, 0, 0x9D)
        write = self.u32(RING_B_WRITE)
        read = self.u32(RING_B_READ)
        if write - read >= RING_B_SLOTS:
            return {"status": "ring_b_full", "read": read, "write": write}
        slot = RING_B_BASE + (write & (RING_B_SLOTS - 1)) * RING_B_STRIDE
        ok = (self.write(slot, adr) and self.write(slot + RING_B_PAYLOAD, payload)
              and self.write(slot + RING_B_LENGTH, struct.pack("<I", len(payload)))
              and self.w32(RING_B_WRITE, write + 1))
        return {"status": "queued" if ok else "write_failed", "slot": hex(slot),
                "write_cursor": write, "payload_length": len(payload)}

    def set_ring_a_drain(self, enabled: bool) -> dict:
        """Stop/restore the engine's own loopback outbox drain 0x674F30.

        With the drain stopped, packets sent to NA_LOOPBACK stay in ring A and
        the external bridge can forward them to a real server.  The patch only
        replaces the 3-byte prologue with `xor eax,eax; ret` and is reversible.
        """
        before = self.read(RING_A_DRAIN_FN, 3)
        if before is None:
            return {"status": "read_failed"}
        if enabled:
            ok = self.write(RING_A_DRAIN_FN, b"\x31\xc0\xc3")
            status = "drain_blocked"
        else:
            ok = self.write(RING_A_DRAIN_FN, RING_A_DRAIN_ORIGINAL)
            status = "drain_restored"
        after = self.read(RING_A_DRAIN_FN, 3)
        return {"status": status if ok else "write_failed",
                "before": before.hex(), "after": (after or b"").hex()}

    def set_heartbeat(self, enabled: bool) -> dict:
        """Patch/restore the encrypted heartbeat sender 0x5B3160.

        Build 1649370 derives the heartbeat vtable call as
        `[obj+0x2C] ^ [obj+0x30] ^ [0xE60B78]`; the offline build does not
        initialize that key, so the first heartbeat after gamestate executes a
        garbage address (observed 0xC652C1DA).  Skipping the sender keeps the
        client alive; the bridge can send keepalive packets instead.
        """
        before = self.read(HEARTBEAT_FN, 3)
        if before is None:
            return {"status": "read_failed"}
        if enabled:
            ok = self.write(HEARTBEAT_FN, b"\x31\xc0\xc3")
            status = "heartbeat_blocked"
        else:
            ok = self.write(HEARTBEAT_FN, HEARTBEAT_ORIGINAL)
            status = "heartbeat_restored"
        after = self.read(HEARTBEAT_FN, 3)
        return {"status": status if ok else "write_failed",
                "before": before.hex(), "after": (after or b"").hex()}

    def start_challenge(self) -> dict:
        """Put client slot 0 into connection phase 3 with a loopback adr.

        The game's own frame tick calls `0x5C05F0` for phases 3..6; phase 3
        emits `getchallenge 0 "<local challenge>"` through the loopback ring.
        """
        connection = self.connection()
        if not (0x10000 <= connection < 0x7FFF0000):
            return {"status": "connection_invalid", "connection": hex(connection)}
        adr = struct.pack("<I4sHHIII", 2, b"\0\0\0\0", 0, 0, 0, 0, 0x9D)
        ok = (self.write(connection + 0x14, adr)
              and self.w32(connection + 0x30, 0)
              and self.w32(STATE, 3))
        return {"status": "challenge_armed" if ok else "write_failed",
                "connection": hex(connection), "state": self.u32(STATE)}

    def drain_ring_c(self, port: int = 0) -> list[dict]:
        base = RING_C_BASE + port * RING_C_STRIDE
        read = self.u32(base + RING_C_SLOTS * RING_C_SLOT_STRIDE)
        write = self.u32(base + 0x62C4)
        packets = []
        if write - read > RING_C_SLOTS:
            read = write - RING_C_SLOTS
        while read < write:
            slot = base + (read % RING_C_SLOTS) * RING_C_SLOT_STRIDE
            length = self.u32(slot + RING_C_LENGTH)
            if 0 < length <= 0x4E8:
                payload = self.read(slot, length) or b""
                packets.append({
                    "port": port,
                    "slot": hex(slot),
                    "length": length,
                    "sender_port": self.u32(slot + RING_C_PORT),
                    "payload": payload,
                })
            read += 1
            self.w32(base + RING_C_SLOTS * RING_C_SLOT_STRIDE, read)
        return packets

    def drain_ring_a(self) -> list[dict]:
        read = self.u32(RING_A_READ)
        write = self.u32(RING_A_WRITE)
        packets = []
        if write - read > RING_A_SLOTS:
            read = write - RING_A_SLOTS
        while read < write:
            slot = RING_A_BASE + (read & (RING_A_SLOTS - 1)) * RING_A_STRIDE
            length = self.u32(slot + RING_A_LENGTH)
            if 0 < length <= 0x4E6:
                payload = self.read(slot, length) or b""
                packets.append({
                    "slot": hex(slot),
                    "length": length,
                    "type_hint": self.u32(slot + RING_A_TYPE),
                    "payload": payload,
                })
            read += 1
            self.w32(RING_A_READ, read)
        return packets


def cmd_status(client: Client, args) -> dict:
    return client.status()


def cmd_connect(client: Client, args) -> dict:
    address = args.address.encode("latin-1") + b"\0"
    if len(address) > 0x100:
        raise SystemExit("address 超过 0xFF 字节")
    written = client.write(ADDRESS_STRING, address)
    row = client.invoke_sequence([{"target": CONNECT_FN, "args": []}], settle=args.settle)
    row["address_written"] = written
    row["status_after"] = client.status()
    return row


def cmd_pump(client: Client, args) -> dict:
    row = client.invoke_sequence([{"target": PUMP_FN, "args": []}], settle=args.settle)
    row["status_after"] = client.status()
    return row


def cmd_inject(client: Client, args) -> dict:
    row = {"inject": client.inject_oob(args.text, args.adr_type, args.port)}
    if not args.no_pump:
        row["pump"] = client.invoke_sequence([{"target": PUMP_FN, "args": []}], settle=args.settle)
    row["status_after"] = client.status()
    return row


def cmd_drain(client: Client, args) -> dict:
    packets = client.drain_ring_a() if args.ring == "a" else client.drain_ring_c(args.port)
    return {"ring": args.ring, "count": len(packets),
            "packets": [{"length": p["length"], "payload_hex": p["payload"].hex(),
                         "payload_ascii": p["payload"].decode("latin-1", errors="replace")}
                        for p in packets],
            "status_after": client.status()}


def _fix_stats_payload(payload: bytes) -> tuple[bytes, dict]:
    """Rewrite the profile CRC before the 2697 server stores it.

    Build 1649370 uploads one zlib-compressed 32768-byte profile whose first
    dword is not `crc32(profile[4:])` as the 2697 archive handler requires.
    Only the 4-byte check word is replaced; the rest of the profile is kept.
    """
    import zlib as _zlib

    if not payload.startswith(b"\xff\xff\xff\xffstats\0") or len(payload) < 13:
        return payload, {"rewritten": False, "reason": "not_stats"}
    index = payload[10]
    compressed = struct.unpack_from("<H", payload, 11)[0]
    data = payload[13:]
    if not compressed:
        return payload, {"rewritten": False, "reason": "uncompressed"}
    try:
        profile = _zlib.decompress(data)
    except Exception as error:  # noqa: BLE001 - report and keep original
        return payload, {"rewritten": False, "reason": f"inflate_failed:{error}"}
    if len(profile) != 32768:
        return payload, {"rewritten": False, "reason": f"size_{len(profile)}"}
    fixed = bytearray(profile)
    crc = _zlib.crc32(bytes(fixed[4:])) & 0xFFFFFFFF
    struct.pack_into("<I", fixed, 0, crc)
    rebuilt = _zlib.compress(bytes(fixed), 6)
    new_payload = payload[:10] + struct.pack("<H", len(rebuilt)) + rebuilt
    return new_payload, {"rewritten": True, "index": index,
                         "old_crc": struct.unpack_from("<I", profile)[0],
                         "new_crc": crc,
                         "old_compressed": len(data), "new_compressed": len(rebuilt)}


class StatsUploadAssembler:
    """Rebuild a 1649370 stats upload into the 2697 archive format.

    The client may send one compressed block or a whole run of 1238-byte
    blocks whose `compressed` field is the total compressed length.  This
    assembler buffers a run, restores the `crc32(profile[4:])` header, then
    re-compresses and re-chunks so the server accepts it.
    """

    PREFIX = b"\xff\xff\xff\xffstats\0"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.length: int | None = None
        self.chunks: dict[int, bytes] = {}

    @staticmethod
    def _count(length: int) -> int:
        return (length + 1237) // 1238

    def feed(self, payload: bytes) -> list[bytes] | None:
        """Return rebuilt packets, an empty list while buffering, or None."""
        import zlib as _zlib

        if not payload.startswith(self.PREFIX) or len(payload) < 13:
            return None
        index = payload[10]
        length = struct.unpack_from("<H", payload, 11)[0]
        data = payload[13:]
        if length == 0 or length > 32768:
            return None
        count = self._count(length)
        if index >= count:
            return None
        if self.length is not None and (self.length != length or len(self.chunks) > count):
            self.reset()
        self.length = length
        self.chunks[index] = data
        if len(self.chunks) < count:
            return []
        stream = b"".join(self.chunks.get(i, b"") for i in range(count))
        self.reset()
        if len(stream) != length:
            return None
        try:
            profile = _zlib.decompress(stream)
        except Exception:
            return None
        if len(profile) != 32768:
            return None
        fixed = bytearray(profile)
        struct.pack_into("<I", fixed, 0, _zlib.crc32(bytes(fixed[4:])) & 0xFFFFFFFF)
        rebuilt = _zlib.compress(bytes(fixed), 6)
        out = []
        new_count = self._count(len(rebuilt))
        for i in range(new_count):
            part = rebuilt[i * 1238:(i + 1) * 1238]
            out.append(b"\xff\xff\xff\xffstats\0" + bytes([i])
                       + struct.pack("<H", len(rebuilt)) + part)
        return out


def build_fake_stats_packets() -> list[bytes]:
    """Build a complete 2697-format stats upload (25 x 1238-byte blocks).

    Build 1649370's own upload layout does not match the 2697 archive reader,
    so the bridge supplies a syntactically valid profile once the connection
    is established.  Only the 4-byte CRC, the two magic words and zeros are
    present; this is protocol scaffolding, not a player profile claim.
    """
    import zlib as _zlib

    profile = bytearray(32768)
    struct.pack_into("<I", profile, 4, 220)
    struct.pack_into("<I", profile, 8, 0xE4FD5218)
    struct.pack_into("<I", profile, 0, _zlib.crc32(bytes(profile[4:])) & 0xFFFFFFFF)
    stream = _zlib.compress(bytes(profile), 6)
    count = (len(stream) + 1237) // 1238
    return [b"\xff\xff\xff\xffstats\0" + bytes([i]) + struct.pack("<H", len(stream))
            + stream[i * 1238:(i + 1) * 1238] for i in range(count)]


def cmd_forward(client: Client, args) -> dict:
    host, port_text = args.target.rsplit(":", 1)
    target = (host, int(port_text))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    events = []
    sent = 0
    received = 0
    injected = 0
    seen_out: set[bytes] = set()
    stats_assembler = StatsUploadAssembler()
    fake_packets = build_fake_stats_packets() if args.fake_stats else []
    fake_stats_sent = False
    move_due = 0.0
    move_sent = False
    last_keepalive = time.monotonic()
    keepalive_seq = 2
    deadline = time.monotonic() + args.seconds
    last_status = None
    next_retry = 0.0
    if args.block_heartbeat:
        events.append({"t": 0.0, "dir": "heartbeat_patch",
                       "result": client.set_heartbeat(True)})
    if args.start_challenge:
        events.append({"t": 0.0, "dir": "arm", "result": client.start_challenge()})
        next_retry = time.monotonic() + args.retry_seconds
    elif args.connect_address:
        client.write(ADDRESS_STRING, args.connect_address.encode("latin-1") + b"\0")
        result = client.invoke_sequence([{"target": CONNECT_FN, "args": []}], settle=1.0)
        events.append({"t": 0.0, "dir": "connect", "result": result.get("status_after")})
    try:
        while time.monotonic() < deadline:
            progressed = False
            outbox = client.drain_ring_a() + client.drain_ring_c(args.port)
            for packet in outbox:
                payload = packet["payload"]
                stats_note = None
                if args.fake_stats and payload.startswith(StatsUploadAssembler.PREFIX):
                    events.append({"t": round(time.monotonic(), 3), "dir": "drop_client_stats",
                                   "length": len(payload)})
                    progressed = True
                    continue
                if args.fix_stats and payload.startswith(StatsUploadAssembler.PREFIX):
                    rebuilt = stats_assembler.feed(payload)
                    if rebuilt is not None:
                        if not rebuilt:
                            events.append({"t": round(time.monotonic(), 3), "dir": "stats_buffer",
                                           "have": len(stats_assembler.chunks),
                                           "need": stats_assembler._count(stats_assembler.length or 1)})
                            progressed = True
                            continue
                        for item in rebuilt:
                            sock.sendto(item, target)
                            sent += 1
                            events.append({"t": round(time.monotonic(), 3), "dir": "out",
                                           "length": len(item), "stats": "rebuilt"})
                        progressed = True
                        continue
                if args.dedup:
                    key = payload
                    if key in seen_out:
                        progressed = True
                        continue
                    seen_out.add(key)
                sock.sendto(payload, target)
                sent += 1
                event = {"t": round(time.monotonic(), 3), "dir": "out",
                         "length": len(payload),
                         "ascii": payload[:160].decode("latin-1", errors="replace")}
                if stats_note is not None:
                    event["stats"] = stats_note
                events.append(event)
                if (args.fake_stats and not fake_stats_sent
                        and payload.startswith(b"\xff\xff\xff\xffconnect ")):
                    for item in fake_packets:
                        sock.sendto(item, target)
                        sent += 1
                    fake_stats_sent = True
                    move_due = time.monotonic() + args.move_delay
                    events.append({"t": round(time.monotonic(), 3), "dir": "fake_stats",
                                   "blocks": len(fake_packets)})
                progressed = True
            if args.send_move and fake_stats_sent and not move_sent and time.monotonic() >= move_due:
                move = struct.pack("<I", 1) + b"\x00" + bytes([1]) + bytes(200)
                sock.sendto(move, target)
                sent += 1
                move_sent = True
                events.append({"t": round(time.monotonic(), 3), "dir": "clc_move",
                               "length": len(move), "seq": 1})
            if args.keepalive and time.monotonic() - last_keepalive >= 2.0:
                packet = struct.pack("<I", keepalive_seq) + b"\x00" + bytes([1]) + bytes(200)
                sock.sendto(packet, target)
                sent += 1
                keepalive_seq += 1
                last_keepalive = time.monotonic()
                events.append({"t": round(time.monotonic(), 3), "dir": "keepalive",
                               "seq": keepalive_seq - 1})
            for _ in range(64):
                try:
                    data, source = sock.recvfrom(65535)
                except BlockingIOError:
                    break
                except OSError:
                    break
                received += 1
                state_now = client.u32(STATE)
                if not data.startswith(b"\xff\xff\xff\xff") and (
                        args.oob_only or state_now < args.oob_until_state):
                    events.append({"t": round(time.monotonic(), 3), "dir": "drop",
                                   "length": len(data), "state": state_now,
                                   "ascii": data[:32].hex()})
                    progressed = True
                    continue
                # While the client is still priming, empty snapshots would fill
                # the 16-slot ring and push reliable commands out.  Packets
                # carrying the netchan FRAGMENT_BIT are reliable commands or
                # fragments, so only those are injected below the threshold.
                fragment = len(data) >= 4 and (struct.unpack_from("<I", data)[0] & 0x80000000) != 0
                if (not data.startswith(b"\xff\xff\xff\xff") and not fragment
                        and state_now < args.reliable_until_state):
                    events.append({"t": round(time.monotonic(), 3), "dir": "drop_snapshot",
                                   "length": len(data), "state": state_now})
                    progressed = True
                    continue
                result = client.inject_oob_raw(data, args.adr_type, args.port)
                events.append({"t": round(time.monotonic(), 3), "dir": "in",
                               "length": len(data), "source": f"{source[0]}:{source[1]}",
                               "inject": result["status"], "state": state_now,
                               "ascii": data[:160].decode("latin-1", errors="replace")})
                if result["status"] == "queued":
                    injected += 1
                    if args.pump:
                        client.invoke_sequence([{"target": PUMP_FN, "args": []}], settle=0.3)
                progressed = True
            state = client.status()
            if last_status != state["state"]:
                events.append({"t": round(time.monotonic(), 3), "dir": "state",
                               "state": state["state"], "stage": state["stage"]})
                last_status = state["state"]
            if (args.start_challenge and args.retry_seconds > 0
                    and state["state"] == 0 and time.monotonic() >= next_retry):
                events.append({"t": round(time.monotonic(), 3), "dir": "rearm",
                               "result": client.start_challenge()})
                next_retry = time.monotonic() + args.retry_seconds
            if not progressed:
                time.sleep(0.05)
            if len(events) > args.max_events * 2:
                events = events[-args.max_events:]
    finally:
        sock.close()
    return {"sent": sent, "received": received, "injected": injected,
            "events": events[-args.max_events:], "status_after": client.status()}


def _inject_raw(self, data: bytes, adr_type: int = 2, port: int = 0) -> dict:
    adr = struct.pack("<I4sHHIII", adr_type, b"\0\0\0\0", socket.htons(port), 0, 0, 0, 0x9D)
    for _ in range(60):
        write = self.u32(RING_B_WRITE)
        read = self.u32(RING_B_READ)
        if write - read < RING_B_SLOTS:
            break
        time.sleep(0.01)
    else:
        return {"status": "ring_b_full"}
    slot = RING_B_BASE + (write & (RING_B_SLOTS - 1)) * RING_B_STRIDE
    ok = (self.write(slot, adr) and self.write(slot + RING_B_PAYLOAD, data)
          and self.write(slot + RING_B_LENGTH, struct.pack("<I", len(data)))
          and self.w32(RING_B_WRITE, write + 1))
    return {"status": "queued" if ok else "write_failed", "slot": hex(slot)}


Client.inject_oob_raw = _inject_raw  # type: ignore[attr-defined]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("connect")
    p.add_argument("--address", default="localhost")
    p.add_argument("--settle", type=float, default=2.0)
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("pump")
    p.add_argument("--settle", type=float, default=1.0)
    p.set_defaults(func=cmd_pump)

    p = sub.add_parser("inject-oob")
    p.add_argument("--text", required=True)
    p.add_argument("--adr-type", type=int, default=2)
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-pump", action="store_true")
    p.add_argument("--settle", type=float, default=1.0)
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("drain-ring")
    p.add_argument("--ring", choices=("a", "c"), default="a")
    p.add_argument("--port", type=int, default=0)
    p.set_defaults(func=cmd_drain)

    p = sub.add_parser("drain-ring-c")
    p.add_argument("--port", type=int, default=0)
    p.set_defaults(func=cmd_drain, ring="c")

    p = sub.add_parser("forward")
    p.add_argument("--target", default="127.0.0.1:28970")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--adr-type", type=int, default=2)
    p.add_argument("--start-challenge", action="store_true",
                   help="put slot 0 into phase 3 and let the client send getchallenge")
    p.add_argument("--connect-address",
                   help="alternatively call the natural connect entry with this address")
    p.add_argument("--retry-seconds", type=float, default=0.0,
                   help="re-arm phase 3 after this many seconds in phase 0 (0 disables)")
    p.add_argument("--pump", action="store_true",
                   help="also call 0x4F8D70 on the window thread after each injection "
                        "(the engine already drains ring B, so this is only for tests)")
    p.add_argument("--oob-only", action="store_true",
                   help="inject only OOB (FFFFFFFF) replies, drop netchan data for now")
    p.add_argument("--oob-until-state", type=int, default=0,
                   help="drop non-OOB replies while the client phase is below this value")
    p.add_argument("--reliable-until-state", type=int, default=9,
                   help="below this phase, drop non-fragment packets so reliable "
                        "commands are not crowded out of the 16-slot ring")
    p.add_argument("--fix-stats", action="store_true",
                   help="rebuild the 32768-byte profile upload into the 2697 archive format")
    p.add_argument("--fake-stats", action="store_true",
                   help="send a complete 2697-format stats upload right after connect "
                        "and drop the client's own upload")
    p.add_argument("--send-move", action="store_true",
                   help="send the first clc_move ourselves after the fake stats upload")
    p.add_argument("--move-delay", type=float, default=1.5)
    p.add_argument("--keepalive", action="store_true",
                   help="send an OOB heartbeat every 12 s so the server does not time out")
    p.add_argument("--block-heartbeat", action="store_true",
                   help="patch the client's encrypted heartbeat sender (0x5B3160) before running")
    p.add_argument("--dedup", action="store_true",
                   help="forward each identical outgoing payload only once")
    p.add_argument("--max-events", type=int, default=300)
    p.set_defaults(func=cmd_forward)

    p = sub.add_parser("start-challenge")
    p.set_defaults(func=lambda client, args: client.start_challenge())

    p = sub.add_parser("set-state")
    p.add_argument("value", type=lambda value: int(value, 0))
    p.set_defaults(func=lambda client, args: {"status": "state_written",
                                              "value": client.w32(STATE, args.value),
                                              "state": client.u32(STATE)})

    p = sub.add_parser("patch-bytes")
    p.add_argument("address", type=lambda value: int(value, 0))
    p.add_argument("hex", type=str)
    p.set_defaults(func=lambda client, args: {
        "status": "patched",
        "address": hex(args.address),
        "before": client.read(args.address, len(bytes.fromhex(args.hex))).hex(),
        "after": (client.write(args.address, bytes.fromhex(args.hex)) and
                  client.read(args.address, len(bytes.fromhex(args.hex))).hex()),
    })

    p = sub.add_parser("ring-a-drain")
    p.add_argument("state", choices=("block", "restore"))
    p.set_defaults(func=lambda client, args: client.set_ring_a_drain(args.state == "block"))

    p = sub.add_parser("heartbeat")
    p.add_argument("state", choices=("block", "restore"))
    p.set_defaults(func=lambda client, args: client.set_heartbeat(args.state == "block"))

    args = parser.parse_args()
    client = Client()
    try:
        row = args.func(client, args)
    finally:
        client.close()
    text = json.dumps(row, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text.encode("unicode_escape").decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
