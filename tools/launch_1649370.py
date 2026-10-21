"""启动 1649370 离线客户端，绕开 CreateProcessAsUserW 的 WinError 1346。

社区 host（src/codol_rebuild/bootstrap/launch.py）在 ProcessSession.start 里用 low_token()
派生低权限令牌再调 CreateProcessAsUserW；本机那条路径返回 1346
（ERROR_BAD_IMPERSONATION_LEVEL），即使当前令牌是 Primary + Full elevation。

本包装层不修改社区源码，只在 import 之后替换 ProcessSession.start：
用 CreateProcessW 以当前用户令牌挂起创建进程，等原版动态 WFP 守卫确认后再恢复。

**关键**：启动参数必须由本文件显式构造。社区的 tools/launch_offline.py 会在
build_plan() 里补上 --image / --patches / --overlay / --queue-main-menu，
而直接调 bootstrap.launch.main 会跳过那一步 —— 结果是没打补丁、没有明文 fastfile、
也没装菜单激活桩，客户端会在 "无法找到 code_pre_gfx_mp" 之类的错误上停住。

用法：
    C:\\Python314\\python.exe -B -X utf8 tools\\launch_1649370.py --seconds 120
    C:\\Python314\\python.exe -B -X utf8 tools\\launch_1649370.py --full --seconds 120
    C:\\Python314\\python.exe -B -X utf8 tools\\launch_1649370.py --full --local-profile \\
        --room-command room.startgame --breakpoint 0x6398A0:room_startgame_callback
其余社区参数（--prepare-only / --local-profile / --until-close 等）原样透传。
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib
from ctypes import wintypes as W
from pathlib import Path

COMMUNITY_ROOT = Path(r"E:\GAME\COD\1649370")
COMMUNITY_SRC = COMMUNITY_ROOT / "src"
if not COMMUNITY_SRC.is_dir():
    raise SystemExit(f"找不到社区源码目录: {COMMUNITY_SRC}")
if not COMMUNITY_ROOT.is_dir():
    raise SystemExit(f"找不到社区项目目录: {COMMUNITY_ROOT}")
sys.path.insert(0, str(COMMUNITY_SRC))

from codol_rebuild.platform.win32 import K, PTR, SI, PI, SHELLINFO, api, check, wait  # noqa: E402
from codol_rebuild.runtime import session as session_mod  # noqa: E402
from codol_rebuild.adapters.persistence.sqlite_accounts import AccountRepository as OriginalAccountRepository  # noqa: E402
from codol_rebuild.adapters.persistence import game_settings as game_settings_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370.observation_points import BREAKPOINTS  # noqa: E402
from codol_rebuild.adapters.game.v1649370 import menu_queue as menu_queue_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370 import session_bridge as bridge_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370 import ui_movie as ui_movie_mod  # noqa: E402
import codol_rebuild.bootstrap.launch as launch_mod  # noqa: E402

_original_prepare = launch_mod.prepare

# 社区 build_plan() 在参数末尾追加的游戏参数。补丁 0xDBCCF8 把 "set 2451" 改成 "set 2439"，
# 这条 +set 是配套的 —— 少了它客户端会在普通文件打开处报 WIN_FILE_NOT_FOUND（文件名为空）。
GAME_ARGUMENTS = ("+set", "2439", "0")

CREATION_FLAGS = 1030  # CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP | CREATE_UNICODE_ENVIRONMENT

ENV_KEYS = ("SystemRoot", "WINDIR", "COMSPEC", "SystemDrive",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")

# 社区 build_plan() 里固定的目录（本文件自己补，不依赖调用方式）
IMAGE = COMMUNITY_ROOT / "bin" / "v1649370" / "codol1649370-offline.exe"
PATCHES = COMMUNITY_ROOT / "resources" / "v1649370" / "offline-menu-patches.json"
OVERLAY = COMMUNITY_ROOT / "resources" / "v1649370" / "offline-resources"
CLIENT = COMMUNITY_ROOT.parent / "Original Client"
IMAGE_LIBRARY = COMMUNITY_ROOT / "resources" / "v1649370" / "offline-image-library"
LOOSE_LIBRARY = COMMUNITY_ROOT / "resources" / "v1649370" / "offline-loose-library"
PRIVATE_DATA = Path(__file__).resolve().parents[1] / "data" / "v1649370"
ACCOUNT_DB = PRIVATE_DATA / "local.sqlite3"
SETTINGS_DB = PRIVATE_DATA / "game-settings.sqlite3"
OriginalSettingsStore = game_settings_mod.SettingsStore
MAP_PROBE = None
MAP_COMMAND_MODE = "startup"
ROOM_COMMAND = None
ROOM_COMMAND_TIMEOUT = 180
PREFIX_CBUF = None
MAIN_CALL = None
MAIN_CALL_ECX = None
PREWRITES = []
CONNECTION_ADR_PORT = None
LOOPBACK_GUARD = False
LOOPBACK_PORT = 28969
LOOPBACK_GUARD_PATH = Path(__file__).resolve().parents[1] / "tools/ref/client_loopback_guard.exe"
MAP_PROBE_DIRS = {
    "mp_strike_sh": "runs/20261021-1649370-map",
    "mp_arkaden_sh": "runs/20261021-1649370-map-arkaden",
}
MAP_PROBE_FILES = {
    "mp_strike_sh": {
        "mp_strike_sh.ff": "9025460fa95446422729d0881494c6a4a0c376c9d0650bca7dfdf55aaa7b83cb",
        "mp_strike_sh_load.ff": "0d1340d88ba65ce055d5af9c73b33a1d3179b6fa44e0ef5498ee404420613064",
        "mp_strike_sh_const.ff": "f6d077630d5451ac9594e26a6617653ba013f6b2da564ae4648fc084a003326d",
    },
    "mp_arkaden_sh": {
        "mp_arkaden_sh.ff": "62c0629bc5ea8e90e0d9f7d4658a14fc54ad953626e28ae8696e56e0349d8575",
        "mp_arkaden_sh_load.ff": "84c76824cc639c5831906022e5debc91f213daf42ed8f0472900dcd5a2083d41",
        "mp_arkaden_sh_const.ff": "ec9ba6b592751490ab5b7a5a0760e8523f45856649439a1cfa51ebecefc5a3c0",
    },
}


def _parse_prewrite(value: str):
    address, data = value.split("=", 1)
    return int(address, 0), bytes.fromhex(data)


def _build_environment(stage: Path) -> C.Array:
    """按社区的隔离策略构造环境块，只是不再依赖低权限令牌。"""
    env = {k: os.environ[k] for k in ENV_KEYS if k in os.environ}
    env.update({
        "PATH": str(stage) + ";" + os.environ["SystemRoot"] + "\\System32",
        "TEMP": str(stage / "temp"),
        "TMP": str(stage / "temp"),
        "USERPROFILE": str(stage),
        "LOCALAPPDATA": str(stage / "localappdata"),
        "APPDATA": str(stage / "appdata"),
    })
    joined = "\x00".join(f"{k}={v}" for k, v in sorted(env.items())) + "\x00\x00"
    return C.create_unicode_buffer(joined, len(joined))


def _main_thread_call(session, handle, target: int, ecx_value=None) -> dict:
    """在已暂停的游戏主线程上调用一个无参函数。

    在主线程栈上压入原 EIP 作为返回地址，把 EIP 指向分配好的代码 cave：
    pushad; call target; popad; ret。函数返回后 cave 恢复寄存器并 ret 回原
    EIP，主线程继续原流程；调用发生在主线程，不使用远程线程。
    """
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
    k32.GetThreadContext.restype = W.BOOL
    k32.SetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
    k32.SetThreadContext.restype = W.BOOL
    # The target is 32-bit and the host Python is 64-bit; only the Wow64
    # accessors return the x86 CONTEXT for this thread.
    wow64_get = getattr(k32, "Wow64GetThreadContext", None)
    wow64_set = getattr(k32, "Wow64SetThreadContext", None)
    if wow64_get and wow64_set:
        wow64_get.argtypes = [W.HANDLE, C.c_void_p]
        wow64_get.restype = W.BOOL
        wow64_set.argtypes = [W.HANDLE, C.c_void_p]
        wow64_set.restype = W.BOOL
        get_context, set_context = wow64_get, wow64_set
    else:
        get_context, set_context = k32.GetThreadContext, k32.SetThreadContext
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k32.FlushInstructionCache.restype = W.BOOL
    context_size, eip_offset, esp_offset = 716, 184, 196
    storage = C.create_string_buffer(context_size + 16)
    aligned = (C.addressof(storage) + 15) & ~15
    C.memset(aligned, 0, context_size)
    C.c_uint32.from_address(aligned).value = 0x00010001  # CONTEXT_i386 | CONTEXT_CONTROL
    if not get_context(session.info.thread, C.c_void_p(aligned)):
        return {"status": "get_context_failed", "error": C.get_last_error()}
    original_eip = C.c_uint32.from_address(aligned + eip_offset).value
    original_esp = C.c_uint32.from_address(aligned + esp_offset).value
    ecx = None
    if ecx_value == "connection":
        buffer = C.create_string_buffer(4)
        got = C.c_size_t()
        if (not k32.ReadProcessMemory(handle, C.c_void_p(0x331C0C8), buffer, 4, C.byref(got))
                or got.value != 4):
            return {"status": "connection_read_failed", "error": C.get_last_error()}
        ecx = struct.unpack("<I", buffer.raw)[0] ^ 0xD362501F
        if not 0x10000 <= ecx < 0x7FFF0000:
            return {"status": "connection_decode_failed", "encoded": buffer.raw.hex()}
    elif ecx_value is not None:
        ecx = int(ecx_value)
    cave = k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40)  # COMMIT|RESERVE, RWX
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    cave = int(cave)
    call_next = cave + 6
    code = b"\x60\xe8" + struct.pack("<I", (target - call_next) & 0xFFFFFFFF) + b"\x61\xc3"
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "cave": hex(cave), "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    if (not k32.WriteProcessMemory(handle, C.c_void_p(original_esp - 4),
                                   C.create_string_buffer(struct.pack("<I", original_eip), 4),
                                   4, C.byref(wrote)) or wrote.value != 4):
        return {"status": "return_address_write_failed", "cave": hex(cave),
                "original_eip": hex(original_eip), "original_esp": hex(original_esp),
                "error": C.get_last_error()}
    C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
    C.c_uint32.from_address(aligned + eip_offset).value = cave
    if ecx is not None:
        C.c_uint32.from_address(aligned + 172).value = ecx
    if not set_context(session.info.thread, C.c_void_p(aligned)):
        return {"status": "set_context_failed", "cave": hex(cave), "error": C.get_last_error()}
    return {"status": "armed", "target": hex(target), "cave": hex(cave),
            "cave_code": code.hex(), "original_eip": hex(original_eip),
            "original_esp": hex(original_esp), "new_esp": hex(original_esp - 4),
            "ecx": hex(ecx) if ecx is not None else None}


def _room_command_injector(session, command: str) -> None:
    """在主线程暂停的瞬间把一条控制台命令写入原生命令缓冲。

    房间内的“准备”控件在当前离线版本中是惰性的，因此包装层必须在游戏主线程
    上补一条命令。这里不调用游戏函数、不伪造地图结果，只复用原生 Cbuf 缓冲：
    先等全局房间对象有效，再暂停主线程，校验 descriptor/临界区，追加文本并
    回读长度，随后恢复主线程让原消费者执行。
    """
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    k32.CloseHandle.argtypes = [W.HANDLE]
    output = session.run_dir / "room-command.json"
    result = {"command": command, "started": time.time(), "status": "waiting"}
    handle = k32.OpenProcess(0x0438, False, session.info.pid)
    if not handle:
        result.update(status="open_process_failed", error=C.get_last_error())
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    def read(va: int, count: int):
        buffer = C.create_string_buffer(count)
        got = C.c_size_t()
        if not k32.ReadProcessMemory(handle, C.c_void_p(va), buffer, count, C.byref(got)) or got.value != count:
            return None
        return buffer.raw

    def u32(va: int):
        data = read(va, 4)
        return struct.unpack("<I", data)[0] if data else None

    try:
        deadline = time.monotonic() + ROOM_COMMAND_TIMEOUT
        room = None
        while time.monotonic() < deadline:
            candidate = u32(0x82E13FC)
            if candidate and 0x10000 <= candidate < 0x7FFF0000:
                marker = u32(candidate + 0x278)
                session_ptr = u32(candidate + 0x1C)
                if marker is not None and marker & 0xFF == 1 and session_ptr:
                    room = candidate
                    break
            time.sleep(0.4)
        if not room:
            result.update(status="room_not_ready")
            return
        result.update(room=hex(room), vtable=hex(u32(room) or 0))
        payload_text = "\n" + command + "\n"
        payload = payload_text.encode("ascii") + b"\0"
        for attempt in range(20):
            descriptor = read(0x76595A4, 12)
            if not descriptor:
                result.update(status="descriptor_unreadable")
                return
            pointer, capacity, length = struct.unpack("<3I", descriptor)
            if pointer != 0x33821B0 or capacity != 0x20000 or length >= capacity:
                result.update(status="descriptor_mismatch", pointer=hex(pointer),
                              capacity=capacity, length=length)
                return
            if length + len(payload) > capacity:
                result.update(status="buffer_full", length=length)
                return
            lock = read(0x81A55A0, 16)
            if not lock:
                result.update(status="lock_unreadable")
                return
            recursion, owner = struct.unpack("<4I", lock)[2:]
            if recursion:
                time.sleep(0.2)
                continue
            if k32.SuspendThread(session.info.thread) == 0xFFFFFFFF:
                result.update(status="suspend_failed", error=C.get_last_error())
                return
            try:
                descriptor = read(0x76595A4, 12)
                pointer, capacity, length = struct.unpack("<3I", descriptor)
                if pointer != 0x33821B0 or capacity != 0x20000 or length + len(payload) > capacity:
                    result.update(status="descriptor_changed", pointer=hex(pointer),
                                  capacity=capacity, length=length)
                    return
                prewrite_rows = []
                for address, data in PREWRITES:
                    wrote = C.c_size_t()
                    if (not k32.WriteProcessMemory(handle, C.c_void_p(address),
                                                   C.create_string_buffer(data, len(data)),
                                                   len(data), C.byref(wrote))
                            or wrote.value != len(data)):
                        result["prewrites"] = prewrite_rows + [
                            {"address": hex(address), "bytes": data.hex(), "status": "write_failed",
                             "error": C.get_last_error()}]
                        result["status"] = "prewrite_failed"
                        return
                    if read(address, len(data)) != data:
                        result["prewrites"] = prewrite_rows + [
                            {"address": hex(address), "bytes": data.hex(), "status": "readback_failed"}]
                        result["status"] = "prewrite_failed"
                        return
                    prewrite_rows.append({"address": hex(address), "bytes": data.hex(), "status": "ok"})
                if prewrite_rows:
                    result["prewrites"] = prewrite_rows
                if CONNECTION_ADR_PORT:
                    encoded = u32(0x331C0C8)
                    connection = (encoded ^ 0xD362501F) if encoded is not None else 0
                    if not 0x10000 <= connection < 0x7FFF0000:
                        result["connection_adr"] = {"status": "invalid_connection",
                                                    "encoded": hex(encoded or 0)}
                        result["status"] = "connection_address_failed"
                        return
                    # 1649370 netadr_t: +0x14 type, +0x18 IPv4 bytes, +0x1c
                    # network-order port. Set type=NA_IP(4) so the sender does
                    # not treat the endpoint as loopback/IPv6/unspecified.
                    adr = struct.pack("<I4sHH", 4, b"\x7f\x00\x00\x01",
                                      socket.htons(CONNECTION_ADR_PORT), 0)
                    target_address = connection + 0x14
                    wrote = C.c_size_t()
                    if (not k32.WriteProcessMemory(handle, C.c_void_p(target_address),
                                                   C.create_string_buffer(adr, len(adr)),
                                                   len(adr), C.byref(wrote))
                            or wrote.value != len(adr) or read(target_address, len(adr)) != adr):
                        result["connection_adr"] = {"status": "write_failed",
                                                    "connection": hex(connection),
                                                    "address": hex(target_address),
                                                    "error": C.get_last_error()}
                        result["status"] = "connection_address_failed"
                        return
                    result["connection_adr"] = {"status": "ok", "connection": hex(connection),
                                                "address": hex(target_address),
                                                "bytes": adr.hex(),
                                                "port": CONNECTION_ADR_PORT,
                                                "ip": "127.0.0.1"}
                wrote = C.c_size_t()
                if not k32.WriteProcessMemory(handle, C.c_void_p(pointer + length),
                                              C.create_string_buffer(payload, len(payload)),
                                              len(payload), C.byref(wrote)) or wrote.value != len(payload):
                    result.update(status="payload_write_failed", error=C.get_last_error())
                    return
                new_length = length + len(payload_text)
                length_bytes = struct.pack("<I", new_length)
                if not k32.WriteProcessMemory(handle, C.c_void_p(0x76595AC),
                                              C.create_string_buffer(length_bytes, 4),
                                              4, C.byref(wrote)) or wrote.value != 4:
                    result.update(status="length_write_failed", error=C.get_last_error())
                    return
                if read(0x76595A4, 12) != struct.pack("<3I", pointer, capacity, new_length):
                    result.update(status="readback_failed")
                    return
                result.update(status="queued", length_before=length, length_after=new_length,
                              pointer=hex(pointer), payload_address=hex(pointer + length),
                              attempt=attempt + 1)
                if MAIN_CALL:
                    try:
                        result["main_call"] = _main_thread_call(session, handle, MAIN_CALL, MAIN_CALL_ECX)
                    except Exception as error:  # noqa: BLE001 - report, never hide
                        result["main_call"] = {"status": "exception", "error": repr(error)}
                return
            finally:
                k32.ResumeThread(session.info.thread)
        result.update(status="command_lock_busy")
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] room command:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def patched_start(self, exe, settings_session) -> None:
    """替换令牌派生；仍须等动态 WFP 守卫确认后才恢复客户端。"""
    self.settings = settings_session

    si = SI()
    si.cb = C.sizeof(si)

    baseline = settings_session.baseline
    display_defaults = [] if "config_mp.cfg" in baseline else ["+set", "r_displayMode", "windowed"]
    # 显式钉住文件系统根；否则 FS 打开 main/fileSysCheck.cfg 会返回 -7，
    # 随后 Com_Error(WIN_FILE_NOT_FOUND) 把 %s 硬编码成 NULL，只显示空文件名。
    fs_paths = ["+set", "fs_basepath", f'"{self.stage}"',
                "+set", "fs_homepath", f'"{self.stage}"']
    command_line = subprocess.list2cmdline(
        [str(exe), "-q", *display_defaults, *fs_paths, *self.args.argument])
    self.log["command_line"] = command_line
    command = C.create_unicode_buffer(command_line)

    environment = _build_environment(self.stage)

    check(api(K, "CreateProcessW", W.BOOL,
              W.LPCWSTR, W.LPWSTR, PTR, PTR, W.BOOL, W.DWORD,
              PTR, W.LPCWSTR, C.POINTER(SI), C.POINTER(PI))(
        str(exe), command, None, None, False, CREATION_FLAGS,
        C.cast(environment, PTR), str(self.stage), C.byref(si), C.byref(self.info)))

    self.log["pid"] = self.info.pid
    self.log["launch_path"] = "CreateProcessW (patched token path, guarded)"
    self.log["token"] = {
        "verified": False,
        "reason": "patched launch bypasses low-token isolation",
    }

    times = [C.c_uint64() for _ in range(4)]
    check(api(K, "GetProcessTimes", W.BOOL, PTR, *[PTR] * 4)(
        self.info.process, *(C.byref(t) for t in times)))
    self.log["creation_time"] = times[0].value
    if LOOPBACK_GUARD:
        if LOOPBACK_PORT == 28969:
            guard_path = LOOPBACK_GUARD_PATH
        else:
            guard_path = LOOPBACK_GUARD_PATH.with_name(f"client_loopback_guard_{LOOPBACK_PORT}.exe")
    else:
        guard_path = self.guard_path
    self.log["guard_mode"] = "loopback-udp-28969" if LOOPBACK_GUARD else "offline-deny-all"
    self.log["guard_sha256"] = hashlib.sha256(guard_path.read_bytes()).hexdigest()
    request = SHELLINFO()
    request.size = C.sizeof(request)
    request.mask = 320
    request.verb = "runas"
    request.file = str(guard_path)
    expected_bound = 0 if self.args.until_close else max(120, self.args.seconds + 60)
    guard_arguments = [str(self.run_dir), str(self.info.pid), str(exe)]
    if LOOPBACK_GUARD:
        # The 2.6.9.7 loopback guard takes run/pid/exe/[bound] and checks the
        # exact image path itself; it permits only UDP 127.0.0.1:28969.
        guard_arguments.append(str(expected_bound))
    else:
        guard_arguments.extend([str(times[0].value), str(expected_bound)])
    request.parameters = subprocess.list2cmdline(guard_arguments)
    request.show = 0
    check(api(C.WinDLL("shell32", use_last_error=True), "ShellExecuteExW",
              W.BOOL, C.POINTER(SHELLINFO))(C.byref(request)))
    self.guard = request.process
    deadline = time.monotonic() + 30
    ready_path = self.run_dir / "guard-ready.json"
    while time.monotonic() < deadline and not ready_path.exists() and wait(self.guard, 100) != 0:
        pass
    if not ready_path.exists():
        raise RuntimeError("动态 WFP 守卫未确认 ready；客户端保持挂起")
    while True:
        try:
            ready = json.loads(ready_path.read_text(encoding="utf-8"))
            break
        except json.JSONDecodeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    if LOOPBACK_GUARD:
        if (ready.get("scope") != f"udp-127.0.0.1:{LOOPBACK_PORT}" or len(ready.get("filter_ids", [])) != 8
                or not ready.get("job_kill_on_close") or ready.get("max_processes") != 1
                or ready.get("child_pid") != self.info.pid
                or not ready.get("dynamic") or ready.get("bound_seconds") != expected_bound):
            raise ValueError("loopback WFP 守卫状态不符；客户端保持挂起")
    elif (ready.get("scope") != "offline-deny-all" or len(ready.get("filter_ids", [])) != 4
            or not ready.get("job_kill_on_close") or ready.get("max_processes") != 1
            or ready.get("child_pid") != self.info.pid
            or int(ready.get("creation_filetime", -1)) != times[0].value
            or not ready.get("dynamic") or ready.get("bound_seconds") != expected_bound):
        raise ValueError("动态 WFP 守卫状态不符；客户端保持挂起")
    self.log["guard"] = ready

    self.phase_done("process-and-uac-guard")

    check(api(K, "DebugSetProcessKillOnExit", W.BOOL, W.BOOL)(True))
    if api(K, "ResumeThread", W.DWORD, PTR)(self.info.thread) == 0xFFFFFFFF:
        raise C.WinError(C.get_last_error())

    self.resumed = True
    self.log["resumed"] = True
    self.log["lifetime"] = "until_client_exit" if self.args.until_close else "bounded_observation"
    if ROOM_COMMAND:
        threading.Thread(target=_room_command_injector, args=(self, ROOM_COMMAND),
                         name="room-command", daemon=True).start()


# 社区 DEPENDENCIES 只覆盖 DLL 与 CEF；原版根目录还有一批数据/配置文件没被复制。
# 少了它们时客户端会弹「无法找到文件''」并提示客户端数据不完整。
EXTRA_ROOT_FILES = (
    "Game.dat",
    "GameBabyConfig.dat",
    "Tenparty.dat",
    "tenslx.dat",
    "stun.ini",
    "BugTrace.ini",
    "cacert.pem",
)


# 0x4F5120 在切主菜单之前打开 fileSysCheck.cfg；找不到就 Com_Error(WIN_FILE_NOT_FOUND)。
# 社区只把它放在 main/ 下，实测仍失败，因此把候选搜索根逐一铺一份来定位真实路径。
_FS_CHECK_SOURCE = OVERLAY / "main" / "fileSysCheck.cfg"
FS_CHECK_CANDIDATES = (
    "",
    "main",
    "client_shipretail",
    "client_shipretail\\chinese",
    "players",
)
# 环境变量 CODOL_FSCHECK_BYTES 可切换内容形态；默认使用已校验的原包 77 字节：
#   empty  -> 0 字节        comment -> 原包 77 字节注释
#   newline-> 单个换行      probe   -> 用 0x4F5120 打开的那个名字当占位
_FS_CHECK_MODE = os.environ.get("CODOL_FSCHECK_BYTES", "comment").lower()
_FF_DIR = OVERLAY / "client_shipretail" / "chinese"


def _ff_names() -> list[str]:
    if not _FF_DIR.is_dir():
        return []
    return sorted(p.name for p in _FF_DIR.glob("*.ff"))


if _FS_CHECK_MODE == "comment":
    FS_CHECK_CONTENT = _FS_CHECK_SOURCE.read_bytes() if _FS_CHECK_SOURCE.is_file() else b""
elif _FS_CHECK_MODE == "newline":
    FS_CHECK_CONTENT = b"\n"
elif _FS_CHECK_MODE == "probe":
    FS_CHECK_CONTENT = b"fileSysCheck.cfg\n"
elif _FS_CHECK_MODE == "list":
    FS_CHECK_CONTENT = ("\n".join(_ff_names()) + "\n").encode("ascii")
elif _FS_CHECK_MODE == "listpath":
    FS_CHECK_CONTENT = ("\n".join("client_shipretail/chinese/" + n for n in _ff_names()) + "\n").encode("ascii")
elif _FS_CHECK_MODE == "listcrlf":
    FS_CHECK_CONTENT = ("\r\n".join(_ff_names()) + "\r\n").encode("ascii")
else:
    FS_CHECK_CONTENT = b""


def patched_prepare(args, run_dir, stage, log, phase_done):
    """先走社区 prepare，再把原版根目录缺的数据/配置文件补进 stage。"""
    result = _original_prepare(args, run_dir, stage, log, phase_done)
    copied = []
    for name in EXTRA_ROOT_FILES:
        source = CLIENT / name
        destination = stage / name
        if not source.is_file():
            continue
        if destination.exists():
            continue
        shutil.copyfile(source, destination)
        copied.append(name)
    if copied:
        log["extra_root_files"] = copied
        print("[patched] copied extra root files:", ",".join(copied), flush=True)

    if MAP_PROBE:
        source_dir = Path(__file__).resolve().parents[1] / MAP_PROBE_DIRS[MAP_PROBE]
        destination_dir = stage / "client_shipretail/chinese"
        destination_dir.mkdir(parents=True, exist_ok=True)
        staged = []
        for name, expected in MAP_PROBE_FILES[MAP_PROBE].items():
            source = source_dir / name
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise ValueError(f"地图探针源文件缺失或指纹不符: {source}")
            destination = destination_dir / name
            shutil.copyfile(source, destination)
            staged.append({"name": name, "sha256": expected, "size": destination.stat().st_size})
        log["map_probe_resources"] = staged

    # 0x4F5120 打开 fileSysCheck.cfg，返回 -7 即 Com_Error("WIN_FILE_NOT_FOUND", NULL)。
    # 这个名字暗示它本应是「文件系统检查清单」，社区写的 77 字节注释版可能被拒。
    # 用一个可控开关逐一试内容形态和搜索根。
    placed = []
    for candidate in FS_CHECK_CANDIDATES:
        destination = stage / candidate / "fileSysCheck.cfg"
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(FS_CHECK_CONTENT)
            placed.append(candidate or ".")
        except OSError:
            pass
    log["filesyscheck_placed"] = placed
    log["filesyscheck_bytes"] = len(FS_CHECK_CONTENT)
    print("[patched] fileSysCheck.cfg (%d bytes) placed in: %s"
          % (len(FS_CHECK_CONTENT), ",".join(placed)), flush=True)
    return result


def build_host_arguments(user_argv: list[str]) -> list[str]:
    global MAP_PROBE, MAP_COMMAND_MODE, ROOM_COMMAND, PREFIX_CBUF, LOOPBACK_GUARD, LOOPBACK_PORT, MAIN_CALL, MAIN_CALL_ECX, PREWRITES, CONNECTION_ADR_PORT
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--name")
    parser.add_argument("--full", action="store_true",
                        help="同时挂载 image/loose 资源库（对应社区 start_client.cmd）")
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--until-close", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--local-profile", action="store_true")
    parser.add_argument("--verify-resources", action="store_true")
    parser.add_argument("--map-probe", choices=tuple(MAP_PROBE_FILES))
    parser.add_argument("--map-command-mode", choices=("startup", "queue", "none"), default="startup")
    parser.add_argument("--audit-breakpoints", action="store_true")
    parser.add_argument("--capture-ui-movie", action="store_true")
    parser.add_argument("--room-command",
                        help="等本地房间有效后，在主线程暂停时把一条 ASCII 控制台命令写入原生命令缓冲")
    parser.add_argument("--prefix-cbuf",
                        help="在 BeforeCbuf 断点处给已生成的命令文本补一个前缀，例如 mmstart")
    parser.add_argument("--loopback-guard", action="store_true",
                        help="使用私有 2.6.9.7 loopback guard：仅允许该进程的 UDP 127.0.0.1:28969")
    parser.add_argument("--loopback-port", type=int, default=28969,
                        help="loopback guard 允许的 UDP 端口；非 28969 时使用打过补丁的私有副本")
    parser.add_argument("--main-call", type=lambda value: int(value, 0),
                        help="在 room-command 注入后、主线程仍暂停时调用一个无参函数地址")
    parser.add_argument("--main-call-ecx",
                        help="调用前设置 ECX；填 connection 表示解码后的连接对象指针")
    parser.add_argument("--prewrite", action="append", type=_parse_prewrite, default=[],
                        metavar="ADDRESS=HEX",
                        help="在主线程暂停窗口写入固定内存；可重复")
    parser.add_argument("--connection-adr-port", type=int,
                        help="把解码后的 connection 对象 netadr_t 写成 127.0.0.1:<port>")
    known, passthrough = parser.parse_known_args(user_argv)
    MAP_PROBE = known.map_probe
    MAP_COMMAND_MODE = known.map_command_mode
    ROOM_COMMAND = known.room_command
    PREFIX_CBUF = known.prefix_cbuf
    LOOPBACK_GUARD = known.loopback_guard
    LOOPBACK_PORT = known.loopback_port
    MAIN_CALL = known.main_call
    MAIN_CALL_ECX = known.main_call_ecx
    PREWRITES = known.prewrite
    CONNECTION_ADR_PORT = known.connection_adr_port
    if MAP_COMMAND_MODE != "startup" and not MAP_PROBE:
        parser.error("--map-command-mode queue requires --map-probe")

    session = known.name or ("patched-" + __import__("uuid").uuid4().hex[:8])

    args = ["--name", session,
            "--image", str(IMAGE),
            "--client", str(CLIENT),
            "--patches", str(PATCHES),
            "--overlay", str(OVERLAY),
            "--queue-main-menu",
            "--offline-menu-preview"]

    for path, label in ((IMAGE, "镜像"), (PATCHES, "补丁清单"), (OVERLAY, "overlay")):
        if not path.exists():
            raise SystemExit(f"缺少{label}: {path}")
    if not CLIENT.is_dir():
        raise SystemExit(f"缺少客户端目录: {CLIENT}")

    if known.until_close:
        args.append("--until-close")
    else:
        args += ["--seconds", str(known.seconds if known.seconds is not None else 120)]

    if known.prepare_only:
        args.append("--prepare-only")
    if known.local_profile:
        args.append("--local-profile")
    if known.verify_resources:
        args.append("--verify-resources")

    if known.full:
        for lib in (IMAGE_LIBRARY, LOOSE_LIBRARY):
            if not lib.is_dir():
                raise SystemExit(f"缺少资源库: {lib}")
        args += ["--resource-library", str(IMAGE_LIBRARY),
                 "--loose-library", str(LOOSE_LIBRARY)]

    # 其余参数原样透传（例如 --trace-files、--capture-schema、游戏参数）
    args += [a for a in passthrough if a != "--full"]

    # 社区 build_plan() 固定的观测断点；host 的 DebugLoop 依赖它们介入关键阶段
    for point in BREAKPOINTS:
        args += ["--breakpoint", point]

    # 游戏参数必须放在 -- 之后，否则会被 host 当成自己的参数
    game_arguments = [*GAME_ARGUMENTS]
    if MAP_PROBE and MAP_COMMAND_MODE == "startup":
        game_arguments += ["+devmap", MAP_PROBE]
    args += ["--", *game_arguments]
    return args


def main(argv=None) -> int:
    for database in (ACCOUNT_DB, SETTINGS_DB):
        if not database.is_file():
            raise SystemExit(f"缺少 319 私有档案 {database}；先运行 tools/prepare_1649370_profile.py")
    user = list(sys.argv[1:] if argv is None else argv)
    audit_breakpoints = "--audit-breakpoints" in user
    capture_ui_movie = "--capture-ui-movie" in user
    host_args = build_host_arguments(user)
    if capture_ui_movie:
        session_name = host_args[host_args.index("--name") + 1]
        output = Path(__file__).resolve().parents[1] / "runs" / session_name / "codo-original.gfx"
        original_find_resource_patch = ui_movie_mod.find_resource_patch

        def captured_find_resource_patch(read, regions, rules=None):
            plan = original_find_resource_patch(read, regions, rules)
            movie = zlib.decompress(plan["data_before"])
            if len(movie) != ui_movie_mod.RESOURCE_SIZE or hashlib.sha256(movie).hexdigest() != ui_movie_mod.RESOURCE_SHA256:
                raise ValueError("原始 codo.gfx 指纹不符")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write(movie)
            print("[patched] captured original UI movie:", output, flush=True)
            return plan

        ui_movie_mod.find_resource_patch = captured_find_resource_patch
    original_breakpoint = bridge_mod.GameSessionBridge.breakpoint

    def observed_breakpoint(self, event, address, original, label, row, thread, ctx):
        original_breakpoint(self, event, address, original, label, row, thread, ctx)
        if label == "BeforeCbuf":
            try:
                pointer, capacity, length = struct.unpack("<3I", self.process.read(0x76595A4, 12))
                text = self.process.read(pointer, length).decode("ascii", "replace") if length else ""
                snapshot = {"address": hex(address), "label": label,
                            "pointer": hex(pointer), "capacity": capacity,
                            "length": length, "text": text}
                eax = row.get("registers", {}).get("eax")
                if eax:
                    try:
                        snapshot["eax"] = eax
                        snapshot["eax_string"] = self.process.cstring(int(eax, 0))
                    except (OSError, ValueError) as error:
                        snapshot["eax_string_error"] = str(error)
                if PREFIX_CBUF and length and not text.startswith(PREFIX_CBUF):
                    prefix = PREFIX_CBUF.encode("ascii")
                    new_text = prefix + text.encode("ascii")
                    if len(new_text) >= capacity:
                        snapshot["prefix_error"] = "buffer capacity exceeded"
                    else:
                        self.process.write(pointer, new_text + b"\0")
                        self.process.write(0x76595AC, struct.pack("<I", len(new_text)))
                        if self.process.read(0x76595A4, 12) != struct.pack("<3I", pointer, capacity, len(new_text)):
                            raise ValueError("Cbuf prefix readback mismatch")
                        snapshot["prefix_applied"] = PREFIX_CBUF
                        snapshot["prefixed_length"] = len(new_text)
                self.record({"cbuf_snapshot": snapshot})
            except (OSError, ValueError, struct.error) as error:
                self.record({"cbuf_snapshot_error": str(error)})
        if not audit_breakpoints:
            return
        if label not in ("CRT entry", "Local navigation resource", "Switch to main menu"):
            return
        points = []
        for value in self.args.breakpoint:
            point, name = value.split(":", 1)
            target = int(point, 0)
            armed = self.debug.breaks.get(target)
            actual = self.process.read(target, 1).hex()
            points.append({"address": hex(target), "label": name,
                           "registered": armed is not None,
                           "armed_byte": actual == "cc",
                           "actual_byte": actual,
                           "saved_original": armed[0].hex() if armed else None})
        self.record({"breakpoint_audit": {"phase": label, "points": points}})

    bridge_mod.GameSessionBridge.breakpoint = observed_breakpoint
    if MAP_PROBE and MAP_COMMAND_MODE == "queue":
        menu_queue_mod.COMMAND = ("\nswitchtomainmenu\ndevmap " + MAP_PROBE + "\n").encode("ascii")
        print("[patched] map probe queued after main-menu transition:", MAP_PROBE, flush=True)
    print("[patched] host arguments:", " ".join(host_args), flush=True)
    session_mod.ProcessSession.start = patched_start
    launch_mod.prepare = patched_prepare
    launch_mod.AccountRepository = lambda _community_path: OriginalAccountRepository(ACCOUNT_DB)
    game_settings_mod.SettingsStore = lambda _community_path: OriginalSettingsStore(SETTINGS_DB)
    return launch_mod.main(host_args)


if __name__ == "__main__":
    raise SystemExit(main())
