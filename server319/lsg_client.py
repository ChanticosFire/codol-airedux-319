"""Read the client's live LSG connection fields for the 0x83 challenge.

The 0x82 frame does not carry the challenge; the client compares our 0x83 token
against ``conn+0x5FC`` in its own memory (reference: lsg_echo319.py /
0xBA3BA0 handler memcmp). So the lobby server has to read that field out of the
running game.

This module is read-only: OpenProcess(VM_READ), VirtualQueryEx, ReadProcessMemory.
It never writes to the client.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import subprocess

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

CONN_VTABLE_MARK_OFFSET = 0x638
CHALLENGE_OFFSET = 0x5FC
CLIENT_EXE = "codomp_client_shipretail.exe"


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD),
                ("Protect", wt.DWORD),
                ("Type", wt.DWORD)]


k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = wt.BOOL


def find_client_pids() -> list[int]:
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                             timeout=10).stdout.decode("gbk", "ignore")
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        if CLIENT_EXE in line.lower():
            try:
                pids.append(int(line.split(",")[1].strip('"')))
            except (IndexError, ValueError):
                continue
    return pids


def _open(pid: int):
    return k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)


def _read(handle, address: int, size: int) -> bytes | None:
    # ReadProcessMemory may return fewer bytes than asked for on large regions;
    # loop in 4 MB chunks so scans do not silently miss the tail of a region.
    out = b""
    while len(out) < size:
        chunk = min(size - len(out), 4 * 1024 * 1024)
        buf = ctypes.create_string_buffer(chunk)
        got = ctypes.c_size_t(0)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(address + len(out)), buf, chunk,
                                     ctypes.byref(got)):
            break
        if not got.value:
            break
        out += buf.raw[:got.value]
    return out if out else None


def _u32(handle, address: int) -> int | None:
    data = _read(handle, address, 4)
    return struct.unpack("<I", data)[0] if data and len(data) == 4 else None


def find_conn_candidates(pid: int, mark: int, limit: int = 48) -> list[dict]:
    """Every place the 8-byte mark appears; each candidate records the fields
    the reference uses to recognise a real conn (vtable at +0, stage at +0x5E8)."""
    handle = _open(pid)
    if not handle:
        return []
    pattern = struct.pack("<Q", mark)
    found: list[dict] = []
    address = 0
    try:
        while address < 0x7FFFFFFF and len(found) < limit:
            mbi = MBI()
            if not k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                                      ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize or 0x1000
            base = int(mbi.BaseAddress or address)
            readable = (mbi.State == MEM_COMMIT and size < 0x10000000
                        and not (mbi.Protect & PAGE_GUARD) and mbi.Protect != PAGE_NOACCESS)
            if readable:
                data = _read(handle, base, size)
                if data:
                    start = 0
                    while len(found) < limit:
                        index = data.find(pattern, start)
                        if index < 0:
                            break
                        start = index + 1
                        candidate = base + index - CONN_VTABLE_MARK_OFFSET
                        challenge = _read(handle, candidate + CHALLENGE_OFFSET, 8)
                        if not challenge or len(challenge) != 8 or challenge == b"\x00" * 8:
                            continue
                        found.append({
                            "mark_at": base + index,
                            "conn": candidate,
                            "vtable": _u32(handle, candidate),
                            "stage": _u32(handle, candidate + 0x5E8),
                            "challenge": challenge.hex(),
                        })
            address = base + size
    finally:
        k32.CloseHandle(handle)
    return found


def find_conn_by_vtable(pid: int, vtable: int = 0xD5A50C, limit: int = 16) -> list[dict]:
    """Locate conn objects by their vtable when the mark is not kept in memory."""
    handle = _open(pid)
    if not handle:
        return []
    pattern = struct.pack("<I", vtable)
    found: list[dict] = []
    address = 0
    try:
        while address < 0x7FFFFFFF and len(found) < limit:
            mbi = MBI()
            if not k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                                      ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize or 0x1000
            base = int(mbi.BaseAddress or address)
            readable = (mbi.State == MEM_COMMIT and size < 0x10000000
                        and not (mbi.Protect & PAGE_GUARD) and mbi.Protect != PAGE_NOACCESS)
            if readable:
                data = _read(handle, base, size)
                if data:
                    start = 0
                    while len(found) < limit:
                        index = data.find(pattern, start)
                        if index < 0:
                            break
                        start = index + 1
                        if index % 4:
                            continue
                        obj = base + index
                        stage = _u32(handle, obj + 0x5E8)
                        if stage not in (1, 2, 3):
                            continue
                        found.append({
                            "conn": obj,
                            "vtable": vtable,
                            "stage": stage,
                            "challenge": (_read(handle, obj + CHALLENGE_OFFSET, 8) or b"").hex(),
                        })
            address = base + size
    finally:
        k32.CloseHandle(handle)
    return found


def find_service_conns(pid: int, vtable: int = 0xD5A0C4, limit: int = 16) -> list[dict]:
    """1649370's LSG service vtable is 0xD5A0C4 (holds 0xB98B70 connect and
    0xB98AD0 state machine). The live connection object sits at [service+0x398].

    The heap lives at the high end of the address space, so scan regions in
    descending order and stop at the first hit: the handshake has a short
    deadline and a full low-to-high sweep takes long enough to miss it.
    """
    handle = _open(pid)
    if not handle:
        return []
    regions = []
    address = 0
    try:
        while address < 0x7FFFFFFF:
            mbi = MBI()
            if not k32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi),
                                      ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize or 0x1000
            base = int(mbi.BaseAddress or address)
            address = base + size
            if (mbi.State == MEM_COMMIT and size < 0x10000000
                    and not (mbi.Protect & PAGE_GUARD)
                    and (mbi.Protect & 0xFF) in (0x04, 0x08, 0x40, 0x80)):
                regions.append((base, size))
        pattern = struct.pack("<I", vtable)
        found: list[dict] = []
        for base, size in reversed(regions):
            if len(found) >= limit:
                break
            data = _read(handle, base, size)
            if not data:
                continue
            start = 0
            while len(found) < limit:
                index = data.find(pattern, start)
                if index < 0:
                    break
                start = index + 1
                if index % 4:
                    continue
                obj = base + index
                conn = _u32(handle, obj + 0x398)
                if not conn or conn < 0x10000 or conn % 4:
                    continue
                stage = _u32(handle, conn + 0x5E8)
                if stage not in (1, 2, 3):
                    continue
                challenge = _read(handle, conn + CHALLENGE_OFFSET, 8)
                if not challenge or len(challenge) != 8 or challenge == b"\x00" * 8:
                    continue
                found.append({
                    "service": obj,
                    "conn": conn,
                    "stage": stage,
                    "challenge": challenge.hex(),
                })
    finally:
        k32.CloseHandle(handle)
    return found


def read_region(pid: int, address: int, size: int = 0x40) -> str:
    handle = _open(pid)
    if not handle:
        return ""
    try:
        data = _read(handle, address, size)
        return data.hex() if data else ""
    finally:
        k32.CloseHandle(handle)


def find_conn(pid: int, mark: int, vtable: int | None = None) -> int:
    """Find the LSG conn object by the 8-byte mark we sent in the 0x81 gate."""
    for candidate in find_conn_candidates(pid, mark):
        if vtable is not None and candidate["vtable"] != vtable:
            continue
        if candidate["stage"] in (1, 2, 3):
            return candidate["conn"]
    return 0


def read_challenge(pid: int, conn: int) -> bytes | None:
    handle = _open(pid)
    if not handle:
        return None
    try:
        data = _read(handle, conn + CHALLENGE_OFFSET, 8)
        return data if data and len(data) == 8 else None
    finally:
        k32.CloseHandle(handle)


def read_u32(pid: int, address: int) -> int | None:
    handle = _open(pid)
    if not handle:
        return None
    try:
        return _u32(handle, address)
    finally:
        k32.CloseHandle(handle)


def find_challenge(pid_hint: int | None, mark: int) -> tuple[int, int, bytes | None]:
    """Return (pid, conn, challenge) for the first client that has a conn."""
    pids = [pid_hint] if pid_hint else find_client_pids()
    for pid in pids:
        if not pid:
            continue
        conn = find_conn(pid, mark)
        if conn:
            return pid, conn, read_challenge(pid, conn)
    return 0, 0, None
