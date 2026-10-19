#!/usr/bin/env python
"""Build-locked launcher for controlled 1649370 startup experiments.

This tool only *creates* a suspended client process, optionally synthesises the
TCLS hand-off shared mapping described by the 1604220 reference research, then
resumes the main thread and records observable behaviour. It does not patch
code, read process memory, inject threads or write to protected sections.

Modes:
  direct     no command line argument (historical baseline)
  tgp        append -src=tgp (the TCLS launch marker seen in the EXE string pool)
  tgp-sign   -src=tgp plus a synthetic TCLS_SHAREDMEMEMORY<PID> mapping

The mapping layout (+0x10 = record offset 0x14, +0x14 = marker length, +0x18 =
marker bytes, view 0xC8) comes from the 1604220 reference. It is a *candidate*
for 1649370 and must be recorded as unverified until the client consumes it.

Safety contract:
  - four Build anchors are hashed before anything is created;
  - the client root must be the owned staged copy under runtime/;
  - evidence JSON never contains memory contents, tickets or peer addresses;
  - only processes whose image lives under the client root are terminated;
  - the mapping handle stays open for the whole observation window.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server319.manifest import ANCHORS, BUILD, verify_client  # noqa: E402

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
PAGE_READWRITE = 0x04
FILE_MAP_ALL_ACCESS = 0x000F001F
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MAP_VIEW_SIZE = 0xC8
RECORD_OFFSET_FIELD = 0x10
RECORD_OFFSET = 0x14          # first u32 of the record is the marker length
MARKER_OFFSET = RECORD_OFFSET + 4
MARKER_LENGTH = 30
# Deterministic project-synthetic marker; never derived from a real ticket.
SYNTHETIC_MARKER = b"CODOL319LAB-HANDOFF-MARKER-30B"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260),
    ]


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wt.DWORD), ("dwLocalAddr", wt.DWORD),
        ("dwLocalPort", wt.DWORD), ("dwRemoteAddr", wt.DWORD),
        ("dwRemotePort", wt.DWORD), ("dwOwningPid", wt.DWORD),
    ]


k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                               wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                               ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
k32.CreateProcessW.restype = wt.BOOL
k32.CreateFileMappingW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
k32.CreateFileMappingW.restype = wt.HANDLE
k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.ResumeThread.restype = wt.DWORD
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = wt.HANDLE
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.GetExitCodeProcess.restype = wt.BOOL
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.TerminateProcess.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32FirstW.restype = wt.BOOL
k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.restype = wt.BOOL
k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
k32.QueryFullProcessImageNameW.restype = wt.BOOL
iphlpapi.GetExtendedTcpTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD), wt.BOOL,
                                         wt.ULONG, ctypes.c_int, wt.ULONG]
iphlpapi.GetExtendedTcpTable.restype = wt.DWORD
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL

TCP_TABLE_OWNER_PID_ALL = 5
AF_INET = 2
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259


def tcp_rows() -> list[dict]:
    size = wt.DWORD(0)
    iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    if size.value == 0:
        return []
    buffer = ctypes.create_string_buffer(size.value)
    rc = iphlpapi.GetExtendedTcpTable(buffer, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    if rc != 0:
        return []
    count = struct.unpack_from("<I", buffer.raw, 0)[0]
    rows = []
    offset = 4
    for _ in range(count):
        state, laddr, lport, raddr, rport, pid = struct.unpack_from("<6I", buffer.raw, offset)
        offset += 24
        rows.append({
            "pid": pid,
            "state": state,
            "local": f"{socket_ip(laddr)}:{socket_port(lport)}",
            "remote": f"{socket_ip(raddr)}:{socket_port(rport)}",
        })
    return rows


def socket_ip(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def socket_port(value: int) -> int:
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)


def process_table() -> list[dict]:
    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        items = []
        if not k32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            items.append({"pid": entry.th32ProcessID, "parent": entry.th32ParentProcessID,
                          "name": entry.szExeFile})
            if not k32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        return items
    finally:
        k32.CloseHandle(snapshot)


def process_image(pid: int) -> str | None:
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wt.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        k32.CloseHandle(handle)


def process_alive(pid: int) -> tuple[bool, int | None]:
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False, None
    try:
        code = wt.DWORD(0)
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False, None
        return code.value == STILL_ACTIVE, code.value
    finally:
        k32.CloseHandle(handle)


def windows_of(pids: set[int]) -> list[dict]:
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _lparam):
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            length = user32.GetWindowTextW(hwnd, None, 0)
            buffer = ctypes.create_unicode_buffer(max(length + 1, 2))
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            found.append({"pid": pid.value, "hwnd": int(hwnd), "title": buffer.value,
                          "visible": bool(user32.IsWindowVisible(hwnd))})
        return True

    user32.EnumWindows(callback, 0)
    return found


def write_mapping(pid: int, log: list[dict]) -> tuple[int | None, dict]:
    name = f"TCLS_SHAREDMEMEMORY{pid}"
    mapping = k32.CreateFileMappingW(INVALID_HANDLE_VALUE, None, PAGE_READWRITE, 0, MAP_VIEW_SIZE, name)
    record = {"name": name, "view_size": MAP_VIEW_SIZE, "created": bool(mapping)}
    if not mapping:
        record["error"] = ctypes.get_last_error()
        log.append({"event": "mapping_failed", **record})
        return None, record
    view = k32.MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, MAP_VIEW_SIZE)
    if not view:
        record["error"] = ctypes.get_last_error()
        log.append({"event": "map_view_failed", **record})
        k32.CloseHandle(mapping)
        return None, record
    buffer = (ctypes.c_char * MAP_VIEW_SIZE).from_address(view)
    ctypes.memset(view, 0, MAP_VIEW_SIZE)
    struct.pack_into("<I", buffer, RECORD_OFFSET_FIELD, RECORD_OFFSET)
    struct.pack_into("<I", buffer, RECORD_OFFSET, MARKER_LENGTH)
    ctypes.memmove(view + MARKER_OFFSET, SYNTHETIC_MARKER, MARKER_LENGTH)
    k32.UnmapViewOfFile(view)
    record.update({
        "record_offset_field": RECORD_OFFSET_FIELD,
        "record_offset": RECORD_OFFSET,
        "marker_offset": MARKER_OFFSET,
        "marker_length": MARKER_LENGTH,
        "marker_sha256": hashlib.sha256(SYNTHETIC_MARKER).hexdigest(),
        "marker_hex": SYNTHETIC_MARKER.hex(),
        "layout_source": "1604220 reference; unverified on Build 1649370",
    })
    log.append({"event": "mapping_written", **record})
    return mapping, record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--mode", choices=["direct", "tgp", "tgp-sign"], default="tgp-sign")
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--sample-ms", type=int, default=1000)
    parser.add_argument("--extra-args", default="")
    args = parser.parse_args()

    root = args.client_dir.resolve(strict=True)
    staged = (REPO_ROOT / "runtime" / "client-1649370").resolve()
    if root != staged:
        print("refusing: client dir is not the owned staged copy", file=sys.stderr)
        return 2
    checks = verify_client(root)
    if not all(check.ok for check in checks):
        print("refusing: Build anchor mismatch " + json.dumps([c.__dict__ for c in checks]), file=sys.stderr)
        return 2
    evidence = args.evidence.resolve()
    evidence.parent.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    exe = root / "codoMP_client_shipRetail.exe"
    command = f'"{exe}"'
    if args.mode in ("tgp", "tgp-sign"):
        command += " -src=tgp"
    if args.extra_args:
        command += " " + args.extra_args

    events: list[dict] = []
    owned: list[int] = []
    mapping_handle = None
    started = time.time()
    record = {
        "build": BUILD,
        "mode": args.mode,
        "root": str(root),
        "command_line": command,
        "anchors": [check.__dict__ for check in checks],
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "seconds": args.seconds,
        "mapping": None,
        "events": events,
    }
    try:
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        pi = PROCESS_INFORMATION()
        if not k32.CreateProcessW(str(exe), ctypes.create_unicode_buffer(command), None, None, False,
                                  CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, None, str(root),
                                  ctypes.byref(si), ctypes.byref(pi)):
            record["error"] = f"CreateProcessW failed {ctypes.get_last_error()}"
            return 2
        pid = pi.dwProcessId
        owned.append(pid)
        events.append({"event": "created_suspended", "pid": pid,
                       "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        if args.mode == "tgp-sign":
            mapping_handle, mapping_record = write_mapping(pid, events)
            record["mapping"] = mapping_record
        k32.ResumeThread(pi.hThread)
        events.append({"event": "resumed", "pid": pid})
        deadline = started + args.seconds
        while time.time() < deadline:
            time.sleep(max(args.sample_ms, 200) / 1000.0)
            alive, exit_code = process_alive(pid)
            table = process_table()
            by_pid = {item["pid"]: item for item in table}
            for item in table:
                cursor = item
                for _ in range(8):
                    cursor = by_pid.get(cursor.get("parent"))
                    if not cursor:
                        break
                    if cursor["pid"] == pid:
                        if item["pid"] not in owned:
                            image = process_image(item["pid"])
                            if image and image.lower().startswith(str(root).lower()):
                                owned.append(item["pid"])
                        break
            rows = [row for row in tcp_rows() if row["pid"] in set(owned)]
            events.append({
                "event": "sample",
                "elapsed_ms": int((time.time() - started) * 1000),
                "alive": alive,
                "exit_code": exit_code,
                "owned_pids": list(owned),
                "windows": windows_of(set(owned)),
                "tcp": rows,
            })
            if not alive:
                break
    finally:
        for owned_pid in sorted(owned, reverse=True):
            image = process_image(owned_pid)
            if image and image.lower().startswith(str(root).lower()):
                handle = k32.OpenProcess(PROCESS_TERMINATE, False, owned_pid)
                if handle:
                    k32.TerminateProcess(handle, 1)
                    k32.CloseHandle(handle)
                    events.append({"event": "terminated_owned", "pid": owned_pid})
        if mapping_handle:
            k32.CloseHandle(mapping_handle)
        remaining = []
        for owned_pid in owned:
            image = process_image(owned_pid)
            if image and image.lower().startswith(str(root).lower()):
                remaining.append(owned_pid)
        events.append({"event": "final", "remaining_owned": remaining,
                       "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        record["ended_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
