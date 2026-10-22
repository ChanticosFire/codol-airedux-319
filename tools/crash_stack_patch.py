"""Extend the host debug loop's crash record with a page-tolerant stack dump.

The host already records registers and tries to read the faulting thread's
stack, but its strict ReadProcessMemory fails when the stack spans an
unmapped page.  This patch wraps `DebugLoop.run` and, for an access violation,
adds the raw stack, the EBP chain and the bytes at EIP using single-page reads.
It only runs inside the 319 launcher process; no community file is modified.
"""
from __future__ import annotations

import ctypes as C
import struct
from ctypes import wintypes as W

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t)]
k32.ReadProcessMemory.restype = W.BOOL

PAGE = 0x1000


def read_tolerant(handle, address: int, size: int) -> bytes | None:
    if not address:
        return None
    start = address & ~(PAGE - 1)
    end = address + size
    out = bytearray()
    page = start
    while page < end:
        buf = C.create_string_buffer(PAGE)
        got = C.c_size_t()
        if k32.ReadProcessMemory(handle, C.c_void_p(page), buf, PAGE, C.byref(got)):
            out.extend(buf.raw[:got.value])
        else:
            out.extend(b"\0" * PAGE)
        page += PAGE
    offset = address - start
    return bytes(out[offset:offset + size])


def _hex_registers(row: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, value in (row.get("registers") or {}).items():
        try:
            out[name] = int(value, 16)
        except (TypeError, ValueError):
            continue
    return out


def enrich(loop, row: dict) -> None:
    registers = _hex_registers(row)
    esp = registers.get("esp")
    ebp = registers.get("ebp")
    eip = registers.get("eip")
    handle = getattr(getattr(loop.process, "info", None), "process", None)
    if not (esp and handle):
        row["stack_unavailable"] = "no handle or esp"
        return
    stack = read_tolerant(handle, (esp - 0x80) & 0xFFFFFFFF, 0x800)
    if stack is not None:
        row["stack_hex"] = stack.hex()
        row["stack_base"] = hex((esp - 0x80) & 0xFFFFFFFF)
    if eip:
        row["eip_bytes"] = (read_tolerant(handle, eip, 64) or b"").hex()
    frames = []
    frame = ebp
    for _ in range(24):
        if not frame or frame < 0x10000:
            break
        blob = read_tolerant(handle, frame, 8)
        if not blob or len(blob) != 8:
            break
        nxt, ret = struct.unpack("<II", blob)
        frames.append({"frame": hex(frame), "return": hex(ret)})
        if nxt <= frame:
            break
        frame = nxt
    row["frames"] = frames


def install() -> bool:
    try:
        from codol_rebuild.runtime import debug_loop
    except ImportError:
        return False
    original = debug_loop.DebugLoop.run

    def run(self):
        original_record = self.record

        def record(row):
            try:
                if isinstance(row, dict) and row.get("exception") == "0xc0000005":
                    enrich(self, row)
            except Exception as error:  # noqa: BLE001 - never break the host loop
                row["stack_patch_error"] = repr(error)
            return original_record(row)

        self.record = record
        try:
            return original(self)
        finally:
            self.record = original_record

    debug_loop.DebugLoop.run = run
    return True
