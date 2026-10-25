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
import types
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

# The community source currently annotates GameEvents.bind_debugger with
# DebugControl before defining that protocol. Defer annotation evaluation in
# our in-memory copy; leave the community file unchanged.
contracts_name = "codol_rebuild.runtime.contracts"
if contracts_name not in sys.modules:
    contracts_path = COMMUNITY_SRC / "codol_rebuild" / "runtime" / "contracts.py"
    contracts_source = contracts_path.read_text(encoding="utf-8")
    contracts_module = types.ModuleType(contracts_name)
    contracts_module.__file__ = str(contracts_path)
    exec(compile("from __future__ import annotations\n" + contracts_source,
                 str(contracts_path), "exec"), contracts_module.__dict__)
    sys.modules[contracts_name] = contracts_module

from codol_rebuild.platform.win32 import K, PTR, SI, PI, SHELLINFO, api, check, wait  # noqa: E402
from codol_rebuild.runtime import session as session_mod  # noqa: E402
from codol_rebuild.adapters.persistence.sqlite_accounts import AccountRepository as OriginalAccountRepository  # noqa: E402
from codol_rebuild.adapters.persistence import game_settings as game_settings_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370.observation_points import BREAKPOINTS  # noqa: E402

# Breakpoint addresses proven safe on this build, and addresses that silently
# break it (hot or mid-function). Patching int3 into a hazard stalls the client
# at state 8 or drops all traces without any error, which cost several sessions
# before it was understood.
SAFE_BREAKPOINTS = {
    0x471D80, 0x671650, 0x671700, 0x471980, 0x471010, 0x471560,
    0x470FF0, 0x471A36, 0x670FF0, 0x670CB0, 0x670D30, 0x6701D0,
    0x670B15, 0x6710BB, 0x4723DD, 0x472401, 0x472424, 0x472445,
    0x4724A5, 0x472810, 0x471000,
}
HAZARD_BREAKPOINTS = {0x4475F0, 0x471B9E, 0x471C5C}


def check_breakpoints(user_args: list[str]) -> None:
    """Reject known-hazard breakpoints and warn about unknown ones."""
    hazardous, unknown = [], []
    for index, value in enumerate(user_args):
        if value != "--breakpoint" or index + 1 >= len(user_args):
            continue
        spec = user_args[index + 1]
        point = spec.split(":", 1)[0]
        try:
            target = int(point, 0)
        except ValueError:
            continue
        if target in HAZARD_BREAKPOINTS:
            hazardous.append(spec)
        elif target not in SAFE_BREAKPOINTS:
            unknown.append(spec)
    if hazardous:
        raise SystemExit(
            " refusing known-hazard breakpoints "
            + ", ".join(hazardous)
            + " - these are hot/mid-function addresses that silently break the client"
              " (see docs/SNAPSHOT-FORMAT.md section 6)")
    for spec in unknown:
        print(f"[breakpoint] warning: {spec} is not in the safe list;"
              " if the run stalls at state 8 or loses all traces, this is why")

from codol_rebuild.adapters.game.v1649370 import menu_queue as menu_queue_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370 import session_bridge as bridge_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370 import ui_movie as ui_movie_mod  # noqa: E402
import codol_rebuild.bootstrap.launch as launch_mod  # noqa: E402

# 崩溃栈补丁：host 的严格读栈在跨页时失败，这里为访问违例补充逐页栈/EBP 链/EIP 字节。
try:
    import crash_stack_patch  # noqa: E402

    crash_stack_patch.install()
except Exception:  # noqa: BLE001 - diagnostics must never block the launcher
    pass

_original_prepare = launch_mod.prepare

# 社区 build_plan() 在参数末尾追加的游戏参数。补丁 0xDBCCF8 把 "set 2451" 改成 "set 2439"，
# 这条 +set 是配套的 —— 少了它客户端会在普通文件打开处报 WIN_FILE_NOT_FOUND（文件名为空）。
GAME_ARGUMENTS = ("+set", "2439", "0", "+set", "cl_timeout", "600", "+set", "cl_connectTimeout", "600", "+cl_demo_play", "testdemo")

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
MAP_LOADSCREEN_PLACEHOLDER = False
MAP_COMPASS_PROBE = False
MAP_LOOSE_CROSSFIRE = False
MAP_LOOSE_GAMETYPE = False
MAP_GAMETYPE_FF = False
MAP_SUNFLARE = False
MAP_LOOSE_CRASH_TROPICAL = False
MAP_LOOSE_SURVIVAL = False
MAP_LOOSE_DMZ = False
MAP_COMMAND_MODE = "startup"
ROOM_COMMAND = None
CBUF_COMMAND = None
ROOM_COMMAND_TIMEOUT = 180
PREFIX_CBUF = None
MAIN_CALL = None
MAIN_CALL_ECX = None
PREWRITES = []
CONNECTION_ADR_PORT = None
TRANSPORT_CONNECT = False
RING_PROBE = False
HOOK_LOOPBACK = False
INJECT_CHALLENGE = False
GAMESTATE_PATH = None
CALL_CHALLENGE_PARSER = False
INIT_TRANSPORT = False
CALL_CHALLENGE_BRANCH = False
RING_TYPE = 2
RAW_UDP_PATCH = False
RAW_UDP_BRANCH = False
BRANCH_NOOP = False
BRANCH_CAPTURE = False
BRANCH_SOCKET = False
BRANCH_SENDTO = False
REMOTE_UDP_SEND = False
INJECT_REMOTE_RESPONSE = False
REMOTE_UDP_CONNECT = False
REMOTE_NETOBJ = False
LOOPBACK_GUARD = False
TCP_LOOPBACK_GUARD = False
LOCAL_AUTH_LSG = False
LOOPBACK_PORT = 28969
LOOPBACK_GUARD_PATH = Path(__file__).resolve().parents[1] / "tools/ref/client_loopback_guard.exe"
TCP_LOOPBACK_GUARD_PATH = Path(__file__).resolve().parents[1] / "runs/guard-build/client_loopback_tcp_guard-fixed.exe"
MAP_PROBE_DIRS = {
    "mp_strike_sh": "runs/20261021-1649370-map",
    "mp_arkaden_sh": "runs/20261021-1649370-map-arkaden",
    "mp_cross_fire": r"E:\GAME\COD\codol-airedux\CODOL-2.6.9.7-Launcher\runtime\game\training-resources\mp_cross_fire\decoded",
    "mp_hardhat_sh": "runs/20261021-1649370-hardhat",
    "mp_cross_fire_native": "runs/20261021-1649370-crossfire-base",
    "mp_nuked_native": "runs/20261021-1649370-nuked",
    "mp_overgrown_native": "runs/20261021-1649370-overgrown",
    "mp_afghan_native": "runs/20261021-1649370-afghan",
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
    "mp_cross_fire": {
        "mp_cross_fire.ff": "19f5b16fff93c03d5530610b2b5cd8d9bd80832c9fa46218382c3cc8cbcc8807",
        "mp_cross_fire_load.ff": "761b6573021fa4676d1e99fbaab1125856b1cf61e44844377347f50b82c813a4",
        "mp_cross_fire_const.ff": "582ed03131f50af71b17b95fd4e9ef1219022719bff73a60a12ea7978b3eec24",
    },
    "mp_hardhat_sh": {
        "mp_hardhat_sh.ff": "6ec34b491d348976570b03344d56ee0479eef5a1e474fa3bf7b59b8a4d2db241",
        "mp_hardhat_sh_load.ff": "29af6bd6c78f01dfd87e394e1fbc4be9feb8b1e8698cafbded6ece2929d7e6b3",
        "mp_hardhat_sh_const.ff": "9b7b13f2b56aa67a0a35875b1e99840e126cc3d24ec8eb08884a072893c389c5",
    },
    "mp_cross_fire_native": {
        "mp_cross_fire.ff": "45b964b1386479d7e86ee8bcff30ed72bbbfbcbeb76dc5cb4b2b8e22b4fb9c7e",
        "mp_cross_fire_load.ff": "dd9caec41616cf1edd6a0320fc3d4bb5887028292f45c9cad798e98c782e5be5",
        "mp_cross_fire_const.ff": "0ca264e7480c48ac61a6a4b1a8c8880654762cdbef62dc7eb631b105f56c8673",
    },
    "mp_nuked_native": {
        "mp_nuked.ff": "cba6309d58ab5614f5ab1eb85238700cf743addc907cc8387ad7d7e8886590a0",
        "mp_nuked_load.ff": "185a2356bd02e415e767f4ebe0a62c3b3268afe22bb18b86e5338b58e68b02a1",
        "mp_nuked_const.ff": "39930bb58190a02aaf1402705240e94ae66a011e2a6f8a488979086f0ad824da",
    },
    "mp_overgrown_native": {
        "mp_overgrown.ff": "b12a175ece0da61e2be320ea412733d7f2875a3c26e758db6c12726d1675ab1a",
        "mp_overgrown_load.ff": "153978e880567df40e8acfee3a98f509803bc23048c2ed01c0e6d929bc5a6304",
        "mp_overgrown_const.ff": "11ee7976f514e77427e42ca4a2e143722a2460ae9214d9c84a352d1dd9f90cc5",
    },
    "mp_afghan_native": {
        "mp_afghan.ff": "1507866c39489bb1055920ba33aac801bf0e12f1985de6bc09160af4fe0466c0",
        "mp_afghan_load.ff": "8af4a2ee8122176445974018e60b4029455edec918c401a65e43ae441ee49586",
        "mp_afghan_const.ff": "5e43f6006428ed2fcedaa4f8a08e954125cc0ba57b6f26c36d1524036d3d5fe4",
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
    C.c_uint32.from_address(aligned).value = 0x00010003  # CONTEXT_i386 | CONTROL | INTEGER
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
    main_map = os.environ.get("CODOL_MAIN_MAP")
    exec_cmd = os.environ.get("CODOL_EXEC_CMD")
    if os.environ.get("CODOL_ROOM_START"):
        code = (b"\x60" + b"\x6a\x00" + b"\x6a\x00" + b"\x6a\x00" +
                b"\xe8" + struct.pack("<i", target - (cave + 12)) + b"\x61\xc3")
        wrote = C.c_size_t()
        if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                       len(code), C.byref(wrote)) or wrote.value != len(code)):
            return {"status": "cave_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    elif os.environ.get("CODOL_MAP_CALL"):
        string_address = cave + 0x800
        name = (os.environ.get("CODOL_MAP_CALL") or "mp_cross_fire").encode("ascii") + b"\x00"
        code = (b"\x60" + b"\x68" + struct.pack("<I", string_address) +
                b"\x6a\x00" + b"\x68" + struct.pack("<I", string_address) +
                b"\xe8" + struct.pack("<i", target - (cave + 18)) +
                b"\x83\xc4\x0c" + b"\x61\xc3")
        wrote = C.c_size_t()
        if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                       len(code), C.byref(wrote)) or wrote.value != len(code)):
            return {"status": "cave_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        if (not k32.WriteProcessMemory(handle, C.c_void_p(string_address),
                                       C.create_string_buffer(name, len(name)),
                                       len(name), C.byref(wrote)) or wrote.value != len(name)):
            return {"status": "string_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
        one = struct.pack("<I", 1)
        k32.WriteProcessMemory(handle, C.c_void_p(0x3306994),
                               C.create_string_buffer(one, 4), 4, C.byref(wrote))
    elif exec_cmd:
        string_address = cave + 0x800
        name = exec_cmd.encode("ascii") + b"\x00"
        code = (b"\x60" + b"\x6a\x00" + b"\x6a\x00" +
                b"\xb8" + struct.pack("<I", string_address) +
                b"\xe8" + struct.pack("<i", target - (cave + 15)) +
                b"\x83\xc4\x08" + b"\x61\xc3")
        wrote = C.c_size_t()
        if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                       len(code), C.byref(wrote)) or wrote.value != len(code)):
            return {"status": "cave_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        if (not k32.WriteProcessMemory(handle, C.c_void_p(string_address),
                                       C.create_string_buffer(name, len(name)),
                                       len(name), C.byref(wrote)) or wrote.value != len(name)):
            return {"status": "string_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    elif os.environ.get("CODOL_CBUF_EXEC"):
        call_next = cave + 10
        code = (b"\x60" + b"\x6a\x00" + b"\x31\xc0" +
                b"\xe8" + struct.pack("<i", target - call_next) + b"\x61\xc3")
        wrote = C.c_size_t()
        if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                       len(code), C.byref(wrote)) or wrote.value != len(code)):
            return {"status": "cave_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    elif main_map:
        string_address = cave + 0x800
        name = main_map.encode("ascii") + b"\x00"
        call_next = cave + 20
        code = (b"\x60" + b"\x68" + struct.pack("<I", string_address) +
                b"\x6a\x00\x6a\x00" + b"\xb9" + struct.pack("<I", 0x4F3890) +
                b"\xe8" + struct.pack("<i", 0x4F2DE0 - call_next) +
                b"\x81\xc4\x0c\x00\x00\x00" +
                b"\xe8" + struct.pack("<i", 0x4F7DA0 - (cave + 31)) + b"\x61\xc3")
        wrote = C.c_size_t()
        if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                       len(code), C.byref(wrote)) or wrote.value != len(code)):
            return {"status": "cave_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        if (not k32.WriteProcessMemory(handle, C.c_void_p(string_address),
                                       C.create_string_buffer(name, len(name)),
                                       len(name), C.byref(wrote)) or wrote.value != len(name)):
            return {"status": "string_write_failed", "cave": hex(cave), "error": C.get_last_error()}
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    else:
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


def _transport_connect_injector(session) -> None:
    """主线程：先让 0x621E50 建传输通道，再调用 0x5C05F0 发 getchallenge。

    这是 1649370 的离线连接缺口：StringToAdr("localhost") 把 adr+0x14 留成
    0x9D（进程内 loopback 标记），连接路径从不经过 0x621E50 建真实通道，
    于是 0x622040 查表越界返回 -7。这里在主线程暂停窗口直接调用通道创建器，
    让它回填 adr+0x14=N，再让连接状态机用该通道发送。
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
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k32.FlushInstructionCache.restype = W.BOOL
    k32.GetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
    k32.SetThreadContext.argtypes = [W.HANDLE, C.c_void_p]
    wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
    wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
    wow64_get.argtypes = [W.HANDLE, C.c_void_p]
    wow64_set.argtypes = [W.HANDLE, C.c_void_p]
    output = session.run_dir / "transport-connect.json"
    result = {"started": time.time(), "status": "waiting", "port": LOOPBACK_PORT}
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

    def call_rel(target: int, at: int) -> bytes:
        return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

    connection = 0
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            stage = u32(0xE59D20) or 0
            encoded = u32(0x331C0C8) or 0
            candidate = encoded ^ 0xD362501F
            if stage >= 4 and 0x10000 <= candidate < 0x7FFF0000:
                connection = candidate
                break
            time.sleep(0.5)
        if not connection:
            result.update(status="connection_not_ready")
            return
        result["state_before"] = u32(0x76446B0)
        result["flag_100260"] = u32(connection + 0x100260)
        result["channel_before"] = u32(connection + 0x28)
        result["t30"] = u32(connection + 0x30)
        result["t8"] = u32(connection + 8)
        if k32.SuspendThread(session.info.thread) == 0xFFFFFFFF:
            result.update(status="suspend_failed", error=C.get_last_error())
            return
        try:
            context_size, eip_offset, esp_offset, ecx_offset = 716, 184, 196, 172
            storage = C.create_string_buffer(context_size + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, context_size)
            C.c_uint32.from_address(aligned).value = 0x00010001
            if not wow64_get(session.info.thread, C.c_void_p(aligned)):
                result.update(status="get_context_failed", error=C.get_last_error())
                return
            original_eip = C.c_uint32.from_address(aligned + eip_offset).value
            original_esp = C.c_uint32.from_address(aligned + esp_offset).value
            cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40))
            if not cave:
                result.update(status="alloc_failed", error=C.get_last_error())
                return
            adr = connection + 0x14
            buf = cave + 0x100
            result_slot = cave + 0x200
            host = u32(0xE85C68) or 0
            biz = (u32(host + 0x1F0) or 0) if host else 0
            gate = (u32(biz + 0x18) or 0) if biz else 0
            result["host"] = hex(host)
            result["biz"] = hex(biz)
            result["gate_before"] = gate
            wrote = C.c_size_t()
            if biz and gate != 1:
                one = struct.pack("<I", 1)
                if (not k32.WriteProcessMemory(handle, C.c_void_p(biz + 0x18),
                                               C.create_string_buffer(one, 4), 4,
                                               C.byref(wrote)) or wrote.value != 4):
                    result.update(status="gate_write_failed", error=C.get_last_error())
                    return
                result["gate_after"] = u32(biz + 0x18)
            adr_bytes = struct.pack("<I4sHHIII", 4, b"\x7f\x00\x00\x01",
                                    socket.htons(LOOPBACK_PORT), 0, 0, 0, 0x9D)
            wrote = C.c_size_t()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(adr), C.create_string_buffer(adr_bytes, len(adr_bytes)),
                                           len(adr_bytes), C.byref(wrote)) or wrote.value != len(adr_bytes)):
                result.update(status="adr_write_failed", error=C.get_last_error())
                return
            if (not k32.WriteProcessMemory(handle, C.c_void_p(buf), C.create_string_buffer(b"xx\0", 3), 3, C.byref(wrote))
                    or wrote.value != 3):
                result.update(status="buf_write_failed", error=C.get_last_error())
                return
            state = struct.pack("<I", 3)
            if (not k32.WriteProcessMemory(handle, C.c_void_p(0x76446B0), C.create_string_buffer(state, 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="state_write_failed", error=C.get_last_error())
                return
            code = b"\x60\x6a\x02"
            code += b"\x68" + struct.pack("<I", buf)
            code += b"\x68" + struct.pack("<I", adr)
            code += call_rel(0x621E50, cave + len(code))
            code += b"\x83\xc4\x0c"
            code += b"\xa3" + struct.pack("<I", result_slot)
            code += b"\xb9" + struct.pack("<I", connection)
            code += call_rel(0x5C05F0, cave + len(code))
            code += b"\x61\xc3"
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(wrote)) or wrote.value != len(code)):
                result.update(status="cave_write_failed", error=C.get_last_error())
                return
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if (not k32.WriteProcessMemory(handle, C.c_void_p(original_esp - 4),
                                           C.create_string_buffer(struct.pack("<I", original_eip), 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="return_write_failed", error=C.get_last_error())
                return
            C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
            C.c_uint32.from_address(aligned + eip_offset).value = cave
            C.c_uint32.from_address(aligned + ecx_offset).value = connection
            if not wow64_set(session.info.thread, C.c_void_p(aligned)):
                result.update(status="set_context_failed", error=C.get_last_error())
                return
            result.update(status="armed", connection=hex(connection), adr=hex(adr),
                          cave=hex(cave), code=code.hex(), original_eip=hex(original_eip),
                          original_esp=hex(original_esp), adr_bytes=adr_bytes.hex())
        finally:
            k32.ResumeThread(session.info.thread)
        time.sleep(8)
        result["result_eax"] = hex(u32(result_slot) or 0)
        result["channel_after"] = hex(u32(connection + 0x28) or 0)
        result["state_after"] = u32(0x76446B0)
        after = read(adr, 0x18)
        result["adr_after"] = after.hex() if after else None
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] transport connect:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _install_loopback_hook(k32, handle) -> dict:
    """在 0x6750A0 入口装持久 cave hook，把每帧 C2S 数据复制到共享缓冲。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualProtectEx.restype = W.BOOL
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    copy_len, seq, buf = cave + 0x1000, cave + 0x1004, cave + 0x1008
    code = b"\x9c\x60\xfc"                  # pushfd; pushad; cld
    code += b"\x8d\x6c\x24\x24"             # lea ebp,[esp+0x24]  (original esp)
    code += b"\x8b\x75\x08"                 # mov esi,[ebp+8]    data
    code += b"\x8b\x4d\x28"                 # mov ecx,[ebp+0x28] length
    code += b"\xba\xe6\x04\x00\x00"         # mov edx,0x4e6
    code += b"\x3b\xca"                     # cmp ecx,edx
    code += b"\x76\x02"                     # jbe +2
    code += b"\x8b\xca"                     # mov ecx,edx
    code += b"\x89\x0d" + struct.pack("<I", copy_len)
    code += b"\xbf" + struct.pack("<I", buf)
    code += b"\xf3\xa4"                     # rep movsb
    code += b"\xff\x05" + struct.pack("<I", seq)
    code += b"\x61\x9d"                     # popad; popfd
    code += b"\x55\x8b\xec\x53\x56"         # original 5 prologue bytes
    code += b"\xe9" + struct.pack("<I", (0x6750A5 - (cave + len(code) + 5)) & 0xFFFFFFFF)
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x6750A0), 5, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x6750A5) & 0xFFFFFFFF)
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x6750A0), C.create_string_buffer(jump, 5), 5,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x6750A0), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x6750A0), 5)
    if not ok or wrote.value != 5:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "copy_len": hex(copy_len),
            "seq": hex(seq), "buf": hex(buf), "code": code.hex()}


def _remote_netobj(session) -> None:
    """在客户端进程内构造一个 0xC7AF2C 网络对象并调用 0xC654A0 建 socket。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p,
                                       W.DWORD, C.POINTER(W.DWORD)]
    k32.CreateRemoteThread.restype = W.HANDLE
    k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k32.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    output = session.run_dir / "remote-netobj.json"
    result = {"started": time.time(), "status": "waiting"}
    handle = k32.OpenProcess(0x0438, False, session.info.pid)
    if not handle:
        result.update(status="open_process_failed", error=C.get_last_error())
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    try:
        time.sleep(8)
        obj = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
        cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
        if not obj or not cave:
            result.update(status="alloc_failed", error=C.get_last_error())
            return
        obj_bytes = bytearray(0x40)
        struct.pack_into("<I", obj_bytes, 0, 0xC7AF2C)
        code = b"\x60\xb9" + struct.pack("<I", obj)
        code += b"\x6a\xff"                      # port = -1 (skip select/bind)
        code += b"\xe8" + struct.pack("<I", (0xC654A0 - (cave + len(code) + 5)) & 0xFFFFFFFF)
        code += b"\x61\xc3"
        wrote = C.c_size_t()
        for address, blob in ((obj, bytes(obj_bytes)), (cave, code)):
            if (not k32.WriteProcessMemory(handle, C.c_void_p(address),
                                           C.create_string_buffer(blob, len(blob)), len(blob),
                                           C.byref(wrote)) or wrote.value != len(blob)):
                result.update(status="write_failed", address=hex(address), error=C.get_last_error())
                return
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
        tid = W.DWORD()
        thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
        if not thread:
            result.update(status="thread_failed", error=C.get_last_error())
            return
        k32.WaitForSingleObject(thread, 5000)
        exit_code = W.DWORD()
        k32.GetExitCodeThread(thread, C.byref(exit_code))
        result.update(thread_id=tid.value, thread_exit=exit_code.value, obj=hex(obj), cave=hex(cave))
        time.sleep(1)
        buffer = C.create_string_buffer(0x40)
        got = C.c_size_t()
        if (k32.ReadProcessMemory(handle, C.c_void_p(obj), buffer, 0x40, C.byref(got))
                and got.value == 0x40):
            result["object_hex"] = buffer.raw.hex()
            result["socket"] = hex(struct.unpack_from("<I", buffer.raw, 0x14)[0])
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] remote netobj:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _remote_udp_send(session) -> None:
    """在客户端进程内新建远程线程，直接 sendto getchallenge。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p,
                                       W.DWORD, C.POINTER(W.DWORD)]
    k32.CreateRemoteThread.restype = W.HANDLE
    k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k32.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    output = session.run_dir / "remote-udp.json"
    payload = b"\xff\xff\xff\xffgetchallenge 0 \"a731af49a6a2c7e2\""
    result = {"started": time.time(), "status": "waiting", "payload": payload.decode("latin-1")}
    handle = k32.OpenProcess(0x0438, False, session.info.pid)
    if not handle:
        result.update(status="open_process_failed", error=C.get_last_error())
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    def call_rel(target: int, at: int) -> bytes:
        return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

    try:
        time.sleep(15)
        cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40))
        if not cave:
            result.update(status="alloc_failed", error=C.get_last_error())
            return
        data = cave + 0x200
        addr = cave + 0x300
        wsadata = cave + 0x400
        out = cave + 0x500
        timeout = cave + 0x600
        recvbuf = cave + 0x700
        fromaddr = cave + 0x800
        fromlen = cave + 0x820
        sockaddr = struct.pack("<HH4s8x", 2, socket.htons(28969), b"\x7f\x00\x00\x01")
        code = b"\x60"
        code += b"\x68" + struct.pack("<I", wsadata)
        code += b"\x68\x02\x02\x00\x00"
        code += b"\xff\x15\x34\x85\xca\x00"       # WSAStartup (stdcall)
        code += b"\x6a\x11\x6a\x02\x6a\x02"
        code += b"\xff\x15\x48\x85\xca\x00"       # socket (stdcall)
        code += b"\x8b\xd8"                       # mov ebx,eax
        code += b"\x6a\x04"
        code += b"\x68" + struct.pack("<I", timeout)
        code += b"\x68\x06\x10\x00\x00"           # SO_RCVTIMEO
        code += b"\x68\xff\xff\x00\x00"           # SOL_SOCKET
        code += b"\x53"
        code += b"\xff\x15\x58\x85\xca\x00"       # setsockopt (stdcall)
        code += b"\x6a\x10"
        code += b"\x68" + struct.pack("<I", addr)
        code += b"\x6a\x00"
        code += b"\x68" + struct.pack("<I", len(payload))
        code += b"\x68" + struct.pack("<I", data)
        code += b"\x53"
        code += b"\xff\x15\x18\x85\xca\x00"       # sendto (stdcall)
        code += b"\xa3" + struct.pack("<I", out)
        code += b"\x68" + struct.pack("<I", fromlen)
        code += b"\x68" + struct.pack("<I", fromaddr)
        code += b"\x6a\x00"
        code += b"\x68\x00\x08\x00\x00"           # recv buffer length 2048
        code += b"\x68" + struct.pack("<I", recvbuf)
        code += b"\x53"
        code += b"\xff\x15\x1c\x85\xca\x00"       # recvfrom (stdcall)
        code += b"\xa3" + struct.pack("<I", out + 4)
        code += b"\x61\xc3"
        wrote = C.c_size_t()
        for address, blob in ((cave, code), (data, payload), (addr, sockaddr),
                              (timeout, struct.pack("<I", 3000)), (fromlen, struct.pack("<I", 16))):
            if (not k32.WriteProcessMemory(handle, C.c_void_p(address),
                                           C.create_string_buffer(blob, len(blob)), len(blob),
                                           C.byref(wrote)) or wrote.value != len(blob)):
                result.update(status="write_failed", address=hex(address), error=C.get_last_error())
                return
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
        tid = W.DWORD()
        thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
        if not thread:
            result.update(status="thread_failed", error=C.get_last_error())
            return
        k32.WaitForSingleObject(thread, 5000)
        exit_code = W.DWORD()
        k32.GetExitCodeThread(thread, C.byref(exit_code))
        result["thread_id"] = tid.value
        result["thread_exit"] = exit_code.value
        time.sleep(2)
        buffer = C.create_string_buffer(4)
        got = C.c_size_t()
        if k32.ReadProcessMemory(handle, C.c_void_p(out), buffer, 4, C.byref(got)) and got.value == 4:
            result["sendto_return"] = struct.unpack("<i", buffer.raw)[0]
        if k32.ReadProcessMemory(handle, C.c_void_p(out + 4), buffer, 4, C.byref(got)) and got.value == 4:
            recv_length = struct.unpack("<i", buffer.raw)[0]
            result["recv_return"] = recv_length
            if 0 < recv_length <= 2048:
                data_buffer = C.create_string_buffer(recv_length)
                if (k32.ReadProcessMemory(handle, C.c_void_p(recvbuf), data_buffer, recv_length,
                                          C.byref(got)) and got.value == recv_length):
                    result["response_hex"] = data_buffer.raw.hex()
                    result["response_ascii"] = data_buffer.raw.decode("latin-1", "replace")
                from_buffer = C.create_string_buffer(16)
                if (k32.ReadProcessMemory(handle, C.c_void_p(fromaddr), from_buffer, 16,
                                          C.byref(got)) and got.value == 16):
                    result["from"] = from_buffer.raw.hex()
                    if INJECT_REMOTE_RESPONSE:
                        cursor_buffer = C.create_string_buffer(4)
                        if (k32.ReadProcessMemory(handle, C.c_void_p(0x7872C04), cursor_buffer, 4,
                                                  C.byref(got)) and got.value == 4):
                            write_cursor = struct.unpack("<I", cursor_buffer.raw)[0]
                            slot = 0x786DBC0 + (write_cursor & 0xF) * 0x504
                            for address, blob in ((slot, from_buffer.raw),
                                                  (slot + 0x18, data_buffer.raw),
                                                  (slot + 0x500, struct.pack("<I", recv_length))):
                                if (not k32.WriteProcessMemory(handle, C.c_void_p(address),
                                                               C.create_string_buffer(blob, len(blob)),
                                                               len(blob), C.byref(got))
                                        or got.value != len(blob)):
                                    result["ring_inject"] = {"status": "write_failed",
                                                             "address": hex(address)}
                                    break
                            else:
                                if (k32.WriteProcessMemory(handle, C.c_void_p(0x7872C04),
                                                           C.create_string_buffer(
                                                               struct.pack("<I", write_cursor + 1), 4),
                                                           4, C.byref(got)) and got.value == 4):
                                    result["ring_inject"] = {"status": "ok",
                                                             "slot": hex(slot),
                                                             "cursor": write_cursor + 1,
                                                             "length": recv_length}
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] remote udp:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _remote_udp_connect(session) -> None:
    """在客户端进程内用固定源端口完成 getchallenge + connect，并保存两个应答。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p,
                                       W.DWORD, C.POINTER(W.DWORD)]
    k32.CreateRemoteThread.restype = W.HANDLE
    k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k32.GetExitCodeThread.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    output = session.run_dir / "remote-udp-connect.json"
    result = {"started": time.time(), "status": "waiting"}
    handle = k32.OpenProcess(0x0438, False, session.info.pid)
    if not handle:
        result.update(status="open_process_failed", error=C.get_last_error())
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    try:
        time.sleep(12)
        local_port = 28970
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", local_port))
        probe.settimeout(3)
        xuid = "a731af49a6a2c7e2"
        challenge_packet = b"\xff\xff\xff\xffgetchallenge 0 \"" + xuid.encode() + b"\""
        probe.sendto(challenge_packet, ("127.0.0.1", 28969))
        challenge, _ = probe.recvfrom(2048)
        probe.close()
        cookie = challenge.split(b"\x00")[0].decode("latin-1").split()[-1]
        name_hex = "player".encode("utf-16-le").hex()
        info = ("\\name\\%s\\xuid\\%s\\challenge\\%s\\natType\\1\\checksum\\0"
                "\\2490\\1649370\\statver\\1") % (name_hex, xuid, cookie)
        connect_packet = ("\xff\xff\xff\xffconnect %s \"%s\"" % (xuid, info)).encode("latin-1")
        result.update(local_port=local_port, cookie=cookie,
                      connect_request=connect_packet.decode("latin-1"))
        cave = int(k32.VirtualAllocEx(handle, None, 0x4000, 0x3000, 0x40))
        if not cave:
            result.update(status="alloc_failed", error=C.get_last_error())
            return
        p1, p2 = cave + 0x200, cave + 0x300
        local_addr, server_addr = cave + 0x500, cave + 0x520
        recv1, recv2 = cave + 0x700, cave + 0x1000
        timeout, fromaddr, fromlen, out = cave + 0x2000, cave + 0x2100, cave + 0x2120, cave + 0x2140
        code = b"\x60"
        code += b"\x68" + struct.pack("<I", cave + 0x2200) + b"\x68\x02\x02\x00\x00"
        code += b"\xff\x15\x34\x85\xca\x00"                 # WSAStartup
        code += b"\x6a\x11\x6a\x02\x6a\x02"
        code += b"\xff\x15\x48\x85\xca\x00\x8b\xd8"           # socket; mov ebx,eax
        code += b"\x6a\x10\x68" + struct.pack("<I", local_addr) + b"\x53"
        code += b"\xff\x15\x54\x85\xca\x00"                 # bind
        code += b"\x6a\x04\x68" + struct.pack("<I", timeout)
        code += b"\x68\x06\x10\x00\x00\x68\xff\xff\x00\x00\x53"
        code += b"\xff\x15\x58\x85\xca\x00"                 # setsockopt
        for payload_addr, payload_len in ((p1, len(challenge_packet)), (p2, len(connect_packet))):
            code += b"\x6a\x10\x68" + struct.pack("<I", server_addr)
            code += b"\x6a\x00\x68" + struct.pack("<I", payload_len)
            code += b"\x68" + struct.pack("<I", payload_addr) + b"\x53"
            code += b"\xff\x15\x18\x85\xca\x00"             # sendto
            code += b"\x68" + struct.pack("<I", fromlen) + b"\x68" + struct.pack("<I", fromaddr)
            code += b"\x6a\x00"
            if payload_addr == p1:
                code += b"\x68\x00\x08\x00\x00\x68" + struct.pack("<I", recv1)
            else:
                code += b"\x68\x00\x10\x00\x00\x68" + struct.pack("<I", recv2)
            code += b"\x53\xff\x15\x1c\x85\xca\x00"         # recvfrom
            code += b"\xa3" + struct.pack("<I", out if payload_addr == p1 else out + 4)
        code += b"\x61\xc3"
        blobs = [
            (cave, code), (p1, challenge_packet), (p2, connect_packet),
            (local_addr, struct.pack("<HH4s8x", 2, socket.htons(local_port), b"\x7f\x00\x00\x01")),
            (server_addr, struct.pack("<HH4s8x", 2, socket.htons(28969), b"\x7f\x00\x00\x01")),
            (timeout, struct.pack("<I", 3000)), (fromlen, struct.pack("<I", 16)),
        ]
        wrote = C.c_size_t()
        for address, blob in blobs:
            if (not k32.WriteProcessMemory(handle, C.c_void_p(address),
                                           C.create_string_buffer(blob, len(blob)), len(blob),
                                           C.byref(wrote)) or wrote.value != len(blob)):
                result.update(status="write_failed", address=hex(address), error=C.get_last_error())
                return
        k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
        tid = W.DWORD()
        thread = k32.CreateRemoteThread(handle, None, 0, C.c_void_p(cave), None, 0, C.byref(tid))
        if not thread:
            result.update(status="thread_failed", error=C.get_last_error())
            return
        k32.WaitForSingleObject(thread, 10000)
        exit_code = W.DWORD()
        k32.GetExitCodeThread(thread, C.byref(exit_code))
        result["thread_id"] = tid.value
        result["thread_exit"] = exit_code.value
        time.sleep(2)
        for index, (length_addr, data_addr) in enumerate(((out, recv1), (out + 4, recv2))):
            length_buffer = C.create_string_buffer(4)
            got = C.c_size_t()
            if k32.ReadProcessMemory(handle, C.c_void_p(length_addr), length_buffer, 4, C.byref(got)) and got.value == 4:
                length = struct.unpack("<i", length_buffer.raw)[0]
                result[f"step{index}_length"] = length
                if 0 < length <= 0x1000:
                    data_buffer = C.create_string_buffer(length)
                    if (k32.ReadProcessMemory(handle, C.c_void_p(data_addr), data_buffer, length,
                                              C.byref(got)) and got.value == length):
                        result[f"step{index}_hex"] = data_buffer.raw.hex()
                        result[f"step{index}_ascii"] = data_buffer.raw.decode("latin-1", "replace")
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] remote udp connect:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _call_challenge_branch(session) -> None:
    """直接进入 0x5C1678 challengeResponse 分支，使用伪造的 EBP 帧。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
    wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
    wow64_get.argtypes = [W.HANDLE, C.c_void_p]
    wow64_set.argtypes = [W.HANDLE, C.c_void_p]
    output = session.run_dir / "challenge-branch.json"
    text = b"challengeResponse -486178985\x00"
    result = {"started": time.time(), "status": "waiting", "text": text.decode("latin-1")}
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

    def call_rel(target: int, at: int) -> bytes:
        return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

    connection = 0
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            stage = u32(0xE59D20) or 0
            encoded = u32(0x331C0C8) or 0
            candidate = encoded ^ 0xD362501F
            if stage >= 4 and 0x10000 <= candidate < 0x7FFF0000:
                connection = candidate
                break
            time.sleep(0.5)
        if not connection:
            result.update(status="connection_not_ready")
            return
        if k32.SuspendThread(session.info.thread) == 0xFFFFFFFF:
            result.update(status="suspend_failed", error=C.get_last_error())
            return
        try:
            context_size, eip_offset, esp_offset = 716, 184, 196
            storage = C.create_string_buffer(context_size + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, context_size)
            C.c_uint32.from_address(aligned).value = 0x00010001
            if not wow64_get(session.info.thread, C.c_void_p(aligned)):
                result.update(status="get_context_failed", error=C.get_last_error())
                return
            original_eip = C.c_uint32.from_address(aligned + eip_offset).value
            original_esp = C.c_uint32.from_address(aligned + esp_offset).value
            cave = int(k32.VirtualAllocEx(handle, None, 0x4000, 0x3000, 0x40))
            if not cave:
                result.update(status="alloc_failed", error=C.get_last_error())
                return
            text_addr = cave + 0x100
            stub = cave + 0x200
            saved_esp = cave + 0x300
            frame = cave + 0x1000
            frame_ebp = frame + 0x2800
            cookie = (u32(0xE3F240) or 0) ^ frame_ebp
            frame_bytes = bytearray(0x3000)
            base = 0x2800
            struct.pack_into("<I", frame_bytes, base, 0)              # saved ebp
            struct.pack_into("<I", frame_bytes, base + 4, stub)       # return
            struct.pack_into("<I", frame_bytes, base + 0xc, 4)        # netadr type
            struct.pack_into("<I", frame_bytes, base + 0x10, 0x0100007F)  # ip
            struct.pack_into("<I", frame_bytes, base + 0x14, 0x00007129)  # port/pad
            struct.pack_into("<I", frame_bytes, base + 0x24, 0)       # channel
            struct.pack_into("<I", frame_bytes, base - 8, cookie & 0xFFFFFFFF)
            wrote = C.c_size_t()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(frame), C.create_string_buffer(bytes(frame_bytes), len(frame_bytes)),
                                           len(frame_bytes), C.byref(wrote)) or wrote.value != len(frame_bytes)):
                result.update(status="frame_write_failed", error=C.get_last_error())
                return
            if (not k32.WriteProcessMemory(handle, C.c_void_p(text_addr),
                                           C.create_string_buffer(text, len(text)), len(text),
                                           C.byref(wrote)) or wrote.value != len(text)):
                result.update(status="text_write_failed", error=C.get_last_error())
                return
            stub_code = b"\x8b\x25" + struct.pack("<I", saved_esp) + b"\x61\xc3"
            if (not k32.WriteProcessMemory(handle, C.c_void_p(stub),
                                           C.create_string_buffer(stub_code, len(stub_code)), len(stub_code),
                                           C.byref(wrote)) or wrote.value != len(stub_code)):
                result.update(status="stub_write_failed", error=C.get_last_error())
                return
            code = b"\x60\x89\x25" + struct.pack("<I", saved_esp)
            code += b"\xbe" + struct.pack("<I", text_addr)
            code += b"\xbd" + struct.pack("<I", frame_ebp)
            code += b"\x31\xdb"
            code += call_rel(0x5C1678, cave + len(code))
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(wrote)) or wrote.value != len(code)):
                result.update(status="cave_write_failed", error=C.get_last_error())
                return
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if (not k32.WriteProcessMemory(handle, C.c_void_p(original_esp - 4),
                                           C.create_string_buffer(struct.pack("<I", original_eip), 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="return_write_failed", error=C.get_last_error())
                return
            C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
            C.c_uint32.from_address(aligned + eip_offset).value = cave
            if not wow64_set(session.info.thread, C.c_void_p(aligned)):
                result.update(status="set_context_failed", error=C.get_last_error())
                return
            result.update(status="armed", connection=hex(connection), cave=hex(cave),
                          frame=hex(frame_ebp), code=code.hex())
        finally:
            k32.ResumeThread(session.info.thread)
        time.sleep(5)
        result["state_after"] = u32(0x76446B0)
        result["channel_after"] = u32(connection + 0x28)
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] challenge branch:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _init_transport(session) -> None:
    """尝试用真实参数调用 0xBB2C40，让 biz+0x18 闸门自然置 1。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
    wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
    wow64_get.argtypes = [W.HANDLE, C.c_void_p]
    wow64_set.argtypes = [W.HANDLE, C.c_void_p]
    output = session.run_dir / "init-transport.json"
    result = {"started": time.time(), "status": "waiting"}
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

    def call_rel(target: int, at: int) -> bytes:
        return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

    connection = 0
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            stage = u32(0xE59D20) or 0
            encoded = u32(0x331C0C8) or 0
            candidate = encoded ^ 0xD362501F
            if stage >= 4 and 0x10000 <= candidate < 0x7FFF0000:
                connection = candidate
                break
            time.sleep(0.5)
        if not connection:
            result.update(status="connection_not_ready")
            return
        host = u32(0xE85C68) or 0
        biz = (u32(host + 0x1F0) or 0) if host else 0
        arg1 = (u32(host + 0xC) or 0) if host else 0
        result.update(host=hex(host), biz=hex(biz), arg1=hex(arg1),
                      connection=hex(connection), gate_before=u32(biz + 0x18) if biz else None)
        if not (host and biz and arg1):
            result.update(status="args_not_ready")
            return
        if k32.SuspendThread(session.info.thread) == 0xFFFFFFFF:
            result.update(status="suspend_failed", error=C.get_last_error())
            return
        try:
            context_size, eip_offset, esp_offset = 716, 184, 196
            storage = C.create_string_buffer(context_size + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, context_size)
            C.c_uint32.from_address(aligned).value = 0x00010001
            if not wow64_get(session.info.thread, C.c_void_p(aligned)):
                result.update(status="get_context_failed", error=C.get_last_error())
                return
            original_eip = C.c_uint32.from_address(aligned + eip_offset).value
            original_esp = C.c_uint32.from_address(aligned + esp_offset).value
            cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
            if not cave:
                result.update(status="alloc_failed", error=C.get_last_error())
                return
            fake = cave + 0x800
            fake_bytes = bytearray(0x100)
            fake_bytes[4:8] = struct.pack("<I", 1)  # refcount used by 0x7F5E40
            wrote = C.c_size_t()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(fake), C.create_string_buffer(bytes(fake_bytes), len(fake_bytes)),
                                           len(fake_bytes), C.byref(wrote)) or wrote.value != len(fake_bytes)):
                result.update(status="fake_write_failed", error=C.get_last_error())
                return
            result["fake"] = hex(fake)
            code = b"\x60"
            code += b"\x68" + struct.pack("<I", fake)
            code += b"\x68" + struct.pack("<I", arg1)
            code += b"\xb9" + struct.pack("<I", biz)
            code += call_rel(0xBB2C40, cave + len(code))
            code += b"\x83\xc4\x08\x61\xc3"
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(wrote)) or wrote.value != len(code)):
                result.update(status="cave_write_failed", error=C.get_last_error())
                return
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if (not k32.WriteProcessMemory(handle, C.c_void_p(original_esp - 4),
                                           C.create_string_buffer(struct.pack("<I", original_eip), 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="return_write_failed", error=C.get_last_error())
                return
            C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
            C.c_uint32.from_address(aligned + eip_offset).value = cave
            if not wow64_set(session.info.thread, C.c_void_p(aligned)):
                result.update(status="set_context_failed", error=C.get_last_error())
                return
            result.update(status="armed", cave=hex(cave), code=code.hex())
        finally:
            k32.ResumeThread(session.info.thread)
        time.sleep(3)
        result["gate_after"] = u32(biz + 0x18)
        result["biz8_after"] = u32(biz + 8)
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] init transport:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _call_challenge_parser(session) -> None:
    """主线程直接调用 0x5C0FD0 解析 challengeResponse，绕过接收环。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
    wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
    wow64_get.argtypes = [W.HANDLE, C.c_void_p]
    wow64_set.argtypes = [W.HANDLE, C.c_void_p]
    output = session.run_dir / "challenge-parser.json"
    text = b"challengeResponse -486178985\x00"
    result = {"started": time.time(), "status": "waiting", "text": text.decode("latin-1")}
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

    def call_rel(target: int, at: int) -> bytes:
        return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

    connection = 0
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            stage = u32(0xE59D20) or 0
            encoded = u32(0x331C0C8) or 0
            candidate = encoded ^ 0xD362501F
            if stage >= 4 and 0x10000 <= candidate < 0x7FFF0000:
                connection = candidate
                break
            time.sleep(0.5)
        if not connection:
            result.update(status="connection_not_ready")
            return
        if k32.SuspendThread(session.info.thread) == 0xFFFFFFFF:
            result.update(status="suspend_failed", error=C.get_last_error())
            return
        try:
            context_size, eip_offset, esp_offset = 716, 184, 196
            storage = C.create_string_buffer(context_size + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, context_size)
            C.c_uint32.from_address(aligned).value = 0x00010001
            if not wow64_get(session.info.thread, C.c_void_p(aligned)):
                result.update(status="get_context_failed", error=C.get_last_error())
                return
            original_eip = C.c_uint32.from_address(aligned + eip_offset).value
            original_esp = C.c_uint32.from_address(aligned + esp_offset).value
            cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
            if not cave:
                result.update(status="alloc_failed", error=C.get_last_error())
                return
            text_addr = cave + 0x100
            wrote = C.c_size_t()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(text_addr),
                                           C.create_string_buffer(text, len(text)), len(text),
                                           C.byref(wrote)) or wrote.value != len(text)):
                result.update(status="text_write_failed", error=C.get_last_error())
                return
            code = b"\x60"
            for value in (0, 0, 0, 0x00007129, 0x0100007F, 4, 0):
                code += b"\x68" + struct.pack("<I", value)
            code += b"\xb8" + struct.pack("<I", text_addr)
            code += call_rel(0x5C0FD0, cave + len(code))
            code += b"\x83\xc4\x1c\x61\xc3"
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(wrote)) or wrote.value != len(code)):
                result.update(status="cave_write_failed", error=C.get_last_error())
                return
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if (not k32.WriteProcessMemory(handle, C.c_void_p(original_esp - 4),
                                           C.create_string_buffer(struct.pack("<I", original_eip), 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="return_write_failed", error=C.get_last_error())
                return
            C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
            C.c_uint32.from_address(aligned + eip_offset).value = cave
            if not wow64_set(session.info.thread, C.c_void_p(aligned)):
                result.update(status="set_context_failed", error=C.get_last_error())
                return
            result.update(status="armed", connection=hex(connection), cave=hex(cave), code=code.hex())
        finally:
            k32.ResumeThread(session.info.thread)
        time.sleep(5)
        result["state_after"] = u32(0x76446B0)
        result["channel_after"] = u32(connection + 0x28)
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] challenge parser:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _inject_challenge_response(session) -> None:
    """向客户端 loopback 接收环写一条 challengeResponse，验证接收路径。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    output = session.run_dir / "challenge-inject.json"
    payload = Path(GAMESTATE_PATH).read_bytes() if GAMESTATE_PATH else b"challengeResponse -486178985\x00"
    result = {"started": time.time(), "payload": payload.hex(), "status": "waiting"}
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
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if (u32(0xE59D20) or 0) >= 4:
                break
            time.sleep(0.5)
        time.sleep(3)
        wrote = C.c_size_t()
        adr = struct.pack("<I4sHHIII", 2, b"\0\0\0\0", socket.htons(28969), 0, 0, 0, 0x9D)
        for _ in range(50):
            write_cursor = u32(0x7872C04) or 0
            read_cursor = u32(0x7872C00) or 0
            if write_cursor - read_cursor < 15:
                index = write_cursor & 0xF
                slot = 0x786DBC0 + index * 0x504
                data = [("adr", slot, adr), ("payload", slot + 0x18, payload),
                        ("length", slot + 0x500, struct.pack("<I", len(payload)))]
                for name, address, blob in data:
                    if (not k32.WriteProcessMemory(handle, C.c_void_p(address),
                                                   C.create_string_buffer(blob, len(blob)), len(blob),
                                                   C.byref(wrote)) or wrote.value != len(blob)):
                        result.update(status=f"{name}_write_failed", address=hex(address),
                                      error=C.get_last_error())
                        return
                if (not k32.WriteProcessMemory(handle, C.c_void_p(0x7872C04),
                                               C.create_string_buffer(struct.pack("<I", write_cursor + 1), 4), 4,
                                               C.byref(wrote)) or wrote.value != 4):
                    result.update(status="cursor_write_failed", error=C.get_last_error())
                    return
                result.update(status="injected", slot=hex(slot), index=index,
                              write_cursor_before=write_cursor, payload_length=len(payload))
                break
            time.sleep(0.2)
        else:
            result.update(status="ring_full")
            return
        time.sleep(5)
        result["read_cursor"] = u32(0x7872C00)
        result["write_cursor"] = u32(0x7872C04)
        result["state_after"] = u32(0x76446B0)
        encoded = u32(0x331C0C8) or 0
        connection = encoded ^ 0xD362501F
        result["connection"] = hex(connection)
        result["channel_after"] = u32(connection + 0x28)
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] challenge inject:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _install_branch_sendto_test(k32, handle) -> dict:
    """无效分支只调用 sendto(-1, data, len, ...)，验证 sendto ABI。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    addr = cave + 0x100
    out = cave + 0x200
    sockaddr = struct.pack("<HH4s8x", 2, socket.htons(28969), b"\x7f\x00\x00\x01")
    code = b"\x60"
    code += b"\x6a\x10"                         # push 16
    code += b"\x68" + struct.pack("<I", addr)   # push addr
    code += b"\x6a\x00"                         # push 0
    code += b"\xff\x75\x08"                     # push [ebp+8] len
    code += b"\xff\x75\x0c"                     # push [ebp+0xc] data
    code += b"\x6a\xff"                         # push -1 (invalid socket)
    code += b"\xff\x15\x18\x85\xca\x00"         # call sendto (stdcall)
    code += b"\xa3" + struct.pack("<I", out)
    code += b"\x61\x31\xdb\xe9"
    code += struct.pack("<I", (0x6221DD - (cave + len(code) + 4)) & 0xFFFFFFFF)
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    if (not k32.WriteProcessMemory(handle, C.c_void_p(addr),
                                   C.create_string_buffer(sockaddr, len(sockaddr)), len(sockaddr),
                                   C.byref(wrote)) or wrote.value != len(sockaddr)):
        return {"status": "addr_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x6221DD) & 0xFFFFFFFF)
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x6221D8), C.create_string_buffer(jump, 5), 5,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x6221D8), 5)
    if not ok or wrote.value != 5:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "out": hex(out), "code": code.hex()}


def _install_branch_socket(k32, handle) -> dict:
    """无效分支只调用 socket(2,2,17)，保存结果后 noop 返回。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    out = cave + 0x200
    wsadata = cave + 0x300
    code = b"\x60"
    code += b"\x68" + struct.pack("<I", wsadata)   # lpWSAData
    code += b"\x68\x02\x02\x00\x00"                # version 0x202
    code += b"\xff\x15\x34\x85\xca\x00"            # call WSAStartup (stdcall)
    code += b"\x6a\x11\x6a\x02\x6a\x02"
    code += b"\xff\x15\x48\x85\xca\x00"            # call socket (stdcall)
    code += b"\xa3" + struct.pack("<I", out)
    code += b"\x61\x31\xdb\xe9"
    code += struct.pack("<I", (0x6221DD - (cave + len(code) + 4)) & 0xFFFFFFFF)
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x6221DD) & 0xFFFFFFFF)
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x6221D8), C.create_string_buffer(jump, 5), 5,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x6221D8), 5)
    if not ok or wrote.value != 5:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "out": hex(out), "code": code.hex()}


def _install_branch_capture(k32, handle) -> dict:
    """把无效分支替换成只记录 [ebp+...] 参数的 cave，然后 noop 返回。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    out = cave + 0x200
    code = b"\x60"                              # pushad
    for offset, slot in ((8, 0), (0xc, 4), (0x10, 8), (0x14, 0xc), (0x18, 0x10),
                         (0x1c, 0x14), (0x20, 0x18), (0x24, 0x1c), (0x28, 0x20)):
        code += b"\x8b\x45" + bytes([offset])    # mov eax,[ebp+offset]
        code += b"\xa3" + struct.pack("<I", out + slot)  # mov [out+slot],eax
    code += b"\x61\x31\xdb\xe9"
    code += struct.pack("<I", (0x6221DD - (cave + len(code) + 4)) & 0xFFFFFFFF)
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x6221DD) & 0xFFFFFFFF)
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x6221D8), C.create_string_buffer(jump, 5), 5,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x6221D8), 5)
    if not ok or wrote.value != 5:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "out": hex(out), "code": code.hex()}


def _install_branch_noop(k32, handle) -> dict:
    """把无效通道分支替换成成功返回（ebx=1 后跳回）。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    code = b"\xbb\x01\x00\x00\x00\xe9" + struct.pack("<I", (0x6221DD - (cave + 10)) & 0xFFFFFFFF)
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x6221DD) & 0xFFFFFFFF)
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x6221D8), C.create_string_buffer(jump, 5), 5,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x6221D8), 5)
    if not ok or wrote.value != 5:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "code": code.hex()}


def _install_raw_udp_branch(k32, handle) -> dict:
    """只替换 0x622040 的无效通道分支，保留原函数其它路径。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    addr = cave + 0x100
    sockaddr = struct.pack("<HH4s8x", 2, socket.htons(28969), b"\x7f\x00\x00\x01")
    code = b"\x60"                              # pushad
    code += b"\x8b\x75\x0c"                     # mov esi,[ebp+0xc] data
    code += b"\x8b\x7d\x28"                     # mov edi,[ebp+0x28] len
    code += b"\x6a\x11\x6a\x02\x6a\x02"         # push 17,2,2
    code += b"\xff\x15\x48\x85\xca\x00"         # call socket (stdcall)
    code += b"\x8b\xd8"                         # mov ebx,eax
    code += b"\x6a\x10"                         # push 16
    code += b"\x68" + struct.pack("<I", addr)   # push sockaddr
    code += b"\x6a\x00\x57\x56\x53"             # push 0,len,data,sock
    code += b"\xff\x15\x18\x85\xca\x00"         # call sendto (stdcall)
    code += b"\x61\x31\xdb"                     # popad; xor ebx,ebx
    code += b"\xe9" + struct.pack("<I", (0x6221DD - (cave + len(code) + 5)) & 0xFFFFFFFF)
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    if (not k32.WriteProcessMemory(handle, C.c_void_p(addr),
                                   C.create_string_buffer(sockaddr, len(sockaddr)), len(sockaddr),
                                   C.byref(wrote)) or wrote.value != len(sockaddr)):
        return {"status": "addr_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x6221DD) & 0xFFFFFFFF)
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x6221D8), C.create_string_buffer(jump, 5), 5,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x6221D8), 5, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x6221D8), 5)
    if not ok or wrote.value != 5:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "code": code.hex(), "sockaddr": sockaddr.hex()}


def _install_raw_udp_patch(k32, handle) -> dict:
    """把 0x622040 发送包装器改成直接 sendto，绕过传输通道表。"""
    k32.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    cave = int(k32.VirtualAllocEx(handle, None, 0x2000, 0x3000, 0x40))
    if not cave:
        return {"status": "alloc_failed", "error": C.get_last_error()}
    addr = cave + 0x100
    sockaddr = struct.pack("<HH4s8x", 2, socket.htons(28969), b"\x7f\x00\x00\x01")
    code = b"\x60"                                  # pushad
    code += b"\x8d\x6c\x24\x24"                     # lea ebp,[esp+0x24]
    code += b"\x8b\x75\x0c"                         # mov esi,[ebp+0xc] data
    code += b"\x8b\x4d\x08"                         # mov ecx,[ebp+8] length
    code += b"\x6a\x11\x6a\x02\x6a\x02"             # push 17,2,2
    code += b"\xff\x15\x48\x85\xca\x00"             # call socket (stdcall)
    code += b"\x8b\xd8"                             # mov ebx,eax
    code += b"\x6a\x10"                             # push 16
    code += b"\x68" + struct.pack("<I", addr)       # push sockaddr
    code += b"\x6a\x00\x51\x56\x53"                 # push 0,len,buf,sock
    code += b"\xff\x15\x18\x85\xca\x00"             # call sendto (stdcall)
    code += b"\x61\x31\xc0\xc3"                     # popad; xor eax,eax; ret
    wrote = C.c_size_t()
    if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                   len(code), C.byref(wrote)) or wrote.value != len(code)):
        return {"status": "cave_write_failed", "error": C.get_last_error()}
    if (not k32.WriteProcessMemory(handle, C.c_void_p(addr),
                                   C.create_string_buffer(sockaddr, len(sockaddr)), len(sockaddr),
                                   C.byref(wrote)) or wrote.value != len(sockaddr)):
        return {"status": "addr_write_failed", "error": C.get_last_error()}
    k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
    old = W.DWORD()
    if not k32.VirtualProtectEx(handle, C.c_void_p(0x622040), 9, 0x40, C.byref(old)):
        return {"status": "protect_failed", "error": C.get_last_error()}
    jump = b"\xe9" + struct.pack("<I", (cave - 0x622049) & 0xFFFFFFFF) + b"\x90" * 4
    ok = k32.WriteProcessMemory(handle, C.c_void_p(0x622040), C.create_string_buffer(jump, 9), 9,
                                C.byref(wrote))
    k32.VirtualProtectEx(handle, C.c_void_p(0x622040), 9, old.value, C.byref(old))
    k32.FlushInstructionCache(handle, C.c_void_p(0x622040), 9)
    if not ok or wrote.value != 9:
        return {"status": "patch_failed", "error": C.get_last_error()}
    return {"status": "ok", "cave": hex(cave), "code": code.hex(), "sockaddr": sockaddr.hex()}


def _ring_probe_injector(session) -> None:
    """把连接 adr 设为 type=2 loopback，调用 0x5C05F0，观察环 A 是否写入 getchallenge。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    k32.VirtualAllocEx.restype = C.c_void_p
    k32.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
    wow64_get = getattr(k32, "Wow64GetThreadContext", k32.GetThreadContext)
    wow64_set = getattr(k32, "Wow64SetThreadContext", k32.SetThreadContext)
    wow64_get.argtypes = [W.HANDLE, C.c_void_p]
    wow64_set.argtypes = [W.HANDLE, C.c_void_p]
    output = session.run_dir / "ring-probe.json"
    result = {"started": time.time(), "status": "waiting", "packets": []}
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

    def call_rel(target: int, at: int) -> bytes:
        return b"\xe8" + struct.pack("<I", (target - (at + 5)) & 0xFFFFFFFF)

    connection = 0
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            stage = u32(0xE59D20) or 0
            encoded = u32(0x331C0C8) or 0
            candidate = encoded ^ 0xD362501F
            if stage >= 4 and 0x10000 <= candidate < 0x7FFF0000:
                connection = candidate
                break
            time.sleep(0.5)
        if not connection:
            result.update(status="connection_not_ready")
            return
        result["state_before"] = u32(0x76446B0)
        result["flag_100260"] = u32(connection + 0x100260)
        result["channel_before"] = u32(connection + 0x28)
        result["t30"] = u32(connection + 0x30)
        result["t8"] = u32(connection + 8)
        if k32.SuspendThread(session.info.thread) == 0xFFFFFFFF:
            result.update(status="suspend_failed", error=C.get_last_error())
            return
        try:
            context_size, eip_offset, esp_offset, ecx_offset = 716, 184, 196, 172
            storage = C.create_string_buffer(context_size + 16)
            aligned = (C.addressof(storage) + 15) & ~15
            C.memset(aligned, 0, context_size)
            C.c_uint32.from_address(aligned).value = 0x00010001
            if not wow64_get(session.info.thread, C.c_void_p(aligned)):
                result.update(status="get_context_failed", error=C.get_last_error())
                return
            original_eip = C.c_uint32.from_address(aligned + eip_offset).value
            original_esp = C.c_uint32.from_address(aligned + esp_offset).value
            cave = int(k32.VirtualAllocEx(handle, None, 0x1000, 0x3000, 0x40))
            if not cave:
                result.update(status="alloc_failed", error=C.get_last_error())
                return
            if HOOK_LOOPBACK:
                result["hook"] = _install_loopback_hook(k32, handle)
                if result["hook"].get("status") != "ok":
                    result.update(status="hook_failed")
                    return
            if RAW_UDP_PATCH:
                result["raw_udp"] = _install_raw_udp_patch(k32, handle)
                if result["raw_udp"].get("status") != "ok":
                    result.update(status="raw_udp_patch_failed")
                    return
            if RAW_UDP_BRANCH:
                result["raw_udp_branch"] = _install_raw_udp_branch(k32, handle)
                if result["raw_udp_branch"].get("status") != "ok":
                    result.update(status="raw_udp_branch_failed")
                    return
            if BRANCH_NOOP:
                result["branch_noop"] = _install_branch_noop(k32, handle)
                if result["branch_noop"].get("status") != "ok":
                    result.update(status="branch_noop_failed")
                    return
            if BRANCH_CAPTURE:
                result["branch_capture"] = _install_branch_capture(k32, handle)
                if result["branch_capture"].get("status") != "ok":
                    result.update(status="branch_capture_failed")
                    return
            if BRANCH_SOCKET:
                result["branch_socket"] = _install_branch_socket(k32, handle)
                if result["branch_socket"].get("status") != "ok":
                    result.update(status="branch_socket_failed")
                    return
            if BRANCH_SENDTO:
                result["branch_sendto"] = _install_branch_sendto_test(k32, handle)
                if result["branch_sendto"].get("status") != "ok":
                    result.update(status="branch_sendto_failed")
                    return
            adr = connection + 0x14
            adr_bytes = struct.pack("<I4sHHIII", RING_TYPE,
                                    b"\x7f\x00\x00\x01" if RING_TYPE == 4 else b"\0\0\0\0",
                                    socket.htons(28969), 0, 0, 0, 0x9D)
            wrote = C.c_size_t()
            if (not k32.WriteProcessMemory(handle, C.c_void_p(adr), C.create_string_buffer(adr_bytes, len(adr_bytes)),
                                           len(adr_bytes), C.byref(wrote)) or wrote.value != len(adr_bytes)):
                result.update(status="adr_write_failed", error=C.get_last_error())
                return
            state = struct.pack("<I", 3)
            if (not k32.WriteProcessMemory(handle, C.c_void_p(0x76446B0), C.create_string_buffer(state, 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="state_write_failed", error=C.get_last_error())
                return
            code = b"\x60\xb9" + struct.pack("<I", connection)
            code += call_rel(0x5C05F0, cave + len(code))
            code += b"\x61\xc3"
            if (not k32.WriteProcessMemory(handle, C.c_void_p(cave), C.create_string_buffer(code, len(code)),
                                           len(code), C.byref(wrote)) or wrote.value != len(code)):
                result.update(status="cave_write_failed", error=C.get_last_error())
                return
            k32.FlushInstructionCache(handle, C.c_void_p(cave), len(code))
            if (not k32.WriteProcessMemory(handle, C.c_void_p(original_esp - 4),
                                           C.create_string_buffer(struct.pack("<I", original_eip), 4), 4,
                                           C.byref(wrote)) or wrote.value != 4):
                result.update(status="return_write_failed", error=C.get_last_error())
                return
            C.c_uint32.from_address(aligned + esp_offset).value = original_esp - 4
            C.c_uint32.from_address(aligned + eip_offset).value = cave
            C.c_uint32.from_address(aligned + ecx_offset).value = connection
            if not wow64_set(session.info.thread, C.c_void_p(aligned)):
                result.update(status="set_context_failed", error=C.get_last_error())
                return
            result.update(status="armed", connection=hex(connection), adr=hex(adr),
                          adr_bytes=adr_bytes.hex(), cave=hex(cave), code=code.hex())
        finally:
            k32.ResumeThread(session.info.thread)
        cursor = u32(0x788680C) or 0
        result["cursor_start"] = hex(cursor)
        end = time.monotonic() + 45
        while time.monotonic() < end:
            current = u32(0x788680C) or 0
            while cursor != current:
                index = cursor & 0x3F
                slot = 0x7872C08 + index * 0x4F0
                length = u32(slot + 0x4E8) or 0
                tag = u32(slot + 0x4EC) or 0
                data = read(slot, min(max(length, 1), 0x200)) or b""
                result["packets"].append({"index": index, "slot": hex(slot), "length": length,
                                          "tag": tag, "data": data.hex(),
                                          "ascii": data.decode("latin-1", "replace")})
                cursor = (cursor + 1) & 0xFFFFFFFF
            time.sleep(0.1)
        result["cursor_end"] = hex(u32(0x788680C) or 0)
        capture = result.get("branch_capture") or {}
        if capture.get("status") == "ok":
            raw = read(int(capture["out"], 16), 0x24) or b""
            result["branch_args"] = list(struct.unpack("<9I", raw)) if len(raw) == 0x24 else raw.hex()
        socket_test = result.get("branch_socket") or {}
        if socket_test.get("status") == "ok":
            result["socket_handle"] = hex(u32(int(socket_test["out"], 16)) or 0)
        sendto_test = result.get("branch_sendto") or {}
        if sendto_test.get("status") == "ok":
            result["sendto_ret"] = hex(u32(int(sendto_test["out"], 16)) or 0)
        hook = result.get("hook") or {}
        if hook.get("status") == "ok":
            seq_value = u32(int(hook["seq"], 16)) or 0
            length = u32(int(hook["copy_len"], 16)) or 0
            data = read(int(hook["buf"], 16), min(max(length, 1), 0x4E6)) or b""
            result["hook_packets"] = {"seq": seq_value, "length": length, "data": data.hex(),
                                      "ascii": data.decode("latin-1", "replace")}
        result["status"] = "done"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] ring probe:", json.dumps(result, ensure_ascii=False), flush=True)
        k32.CloseHandle(handle)


def _cbuf_injector(session, command: str) -> None:
    """在主菜单阶段把一条控制台命令追加到原生 Cbuf，不依赖房间对象。"""
    k32 = C.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    k32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k32.SuspendThread.argtypes = [W.HANDLE]
    k32.SuspendThread.restype = W.DWORD
    k32.ResumeThread.argtypes = [W.HANDLE]
    k32.ResumeThread.restype = W.DWORD
    output = session.run_dir / "cbuf-command.json"
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
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            stage = u32(0xE59D20) or 0
            if stage >= 4:
                break
            time.sleep(0.5)
        payload = ("\n" + command + "\n").encode("ascii") + b"\0"
        for _ in range(30):
            descriptor = read(0x76595A4, 12)
            if not descriptor:
                result.update(status="descriptor_unreadable")
                return
            pointer, capacity, length = struct.unpack("<3I", descriptor)
            if pointer != 0x33821B0 or capacity != 0x20000 or length + len(payload) > capacity:
                result.update(status="descriptor_mismatch", pointer=hex(pointer),
                              capacity=capacity, length=length)
                return
            lock = read(0x81A55A0, 16)
            if not lock:
                result.update(status="lock_unreadable")
                return
            recursion = struct.unpack("<4I", lock)[2]
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
                    result.update(status="descriptor_changed")
                    return
                wrote = C.c_size_t()
                target = 0x33821B0 + length
                if (not k32.WriteProcessMemory(handle, C.c_void_p(target),
                                               C.create_string_buffer(payload, len(payload)),
                                               len(payload), C.byref(wrote))
                        or wrote.value != len(payload)):
                    result.update(status="write_failed", error=C.get_last_error())
                    return
                new_length = length + len(payload)
                if (not k32.WriteProcessMemory(handle, C.c_void_p(0x76595A4 + 8),
                                               C.create_string_buffer(struct.pack("<I", new_length), 4),
                                               4, C.byref(wrote)) or wrote.value != 4):
                    result.update(status="length_failed", error=C.get_last_error())
                    return
                result.update(status="injected", stage=stage, old_length=length,
                              new_length=new_length)
                time.sleep(0.5)
            finally:
                k32.ResumeThread(session.info.thread)
            break
        if result["status"] == "waiting":
            result["status"] = "stage_timeout"
    finally:
        result["finished"] = time.time()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[patched] cbuf command:", json.dumps(result, ensure_ascii=False), flush=True)


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
                if os.environ.get("CODOL_ROOM_START"):
                    try:
                        map_name = b"mp_cross_fire\x00"
                        for address, data in (
                            (room + 0xE360, struct.pack("<I", 0)),
                            (room + 0x105FC, b"\x00"),
                            (room + 0x1061C, b"\x00"),
                            (room + 0x105D8, struct.pack("<I", 1)),
                            (room + 0x168, struct.pack("<I", 0)),
                            (room + 0x16C, struct.pack("<I", len(map_name) - 1)),
                            (room + 0x170, map_name),
                        ):
                            wrote = C.c_size_t()
                            k32.WriteProcessMemory(handle, C.c_void_p(address),
                                                   C.create_string_buffer(data, len(data)),
                                                   len(data), C.byref(wrote))
                        # 0x945CEB: mov esi,[ecx] -> xor esi,esi (avoid invalid container deref)
                        k32.WriteProcessMemory(handle, C.c_void_p(0x945CEB),
                                               C.create_string_buffer(b"\x31\xf6", 2), 2, C.byref(wrote))
                        result["room_start"] = _main_thread_call(session, handle, 0x62F840, room)
                    except Exception as error:  # noqa: BLE001 - report, never hide
                        result["room_start"] = {"status": "exception", "error": repr(error)}
                elif os.environ.get("CODOL_ROOM_READY"):
                    try:
                        result["room_ready"] = _main_thread_call(session, handle, 0x62F840, room)
                    except Exception as error:  # noqa: BLE001 - report, never hide
                        result["room_ready"] = {"status": "exception", "error": repr(error)}
                if os.environ.get("CODOL_MAP_CALL"):
                    try:
                        result["map_call"] = _main_thread_call(session, handle, 0x4F3890, None)
                    except Exception as error:  # noqa: BLE001 - report, never hide
                        result["map_call"] = {"status": "exception", "error": repr(error)}
                elif os.environ.get("CODOL_EXEC_CMD"):
                    try:
                        result["exec_cmd"] = _main_thread_call(session, handle, 0x4F30C0, None)
                    except Exception as error:  # noqa: BLE001 - report, never hide
                        result["exec_cmd"] = {"status": "exception", "error": repr(error)}
                elif os.environ.get("CODOL_CBUF_EXEC"):
                    try:
                        result["cbuf_exec"] = _main_thread_call(session, handle, 0x4F3080, None)
                    except Exception as error:  # noqa: BLE001 - report, never hide
                        result["cbuf_exec"] = {"status": "exception", "error": repr(error)}
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
    if TCP_LOOPBACK_GUARD:
        guard_path = TCP_LOOPBACK_GUARD_PATH
    elif LOOPBACK_GUARD:
        if LOOPBACK_PORT == 28969:
            guard_path = LOOPBACK_GUARD_PATH
        else:
            guard_path = LOOPBACK_GUARD_PATH.with_name(f"client_loopback_guard_{LOOPBACK_PORT}.exe")
    else:
        guard_path = self.guard_path
    self.log["guard_mode"] = ("loopback-tcp-udp-28969" if TCP_LOOPBACK_GUARD else
                              "loopback-udp-28969" if LOOPBACK_GUARD else "offline-deny-all")
    self.log["guard_sha256"] = hashlib.sha256(guard_path.read_bytes()).hexdigest()
    request = SHELLINFO()
    request.size = C.sizeof(request)
    request.mask = 320
    request.verb = "runas"
    request.file = str(guard_path)
    expected_bound = 0 if self.args.until_close else max(120, self.args.seconds + 60)
    guard_arguments = [str(self.run_dir), str(self.info.pid), str(exe)]
    if LOOPBACK_GUARD or TCP_LOOPBACK_GUARD:
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
    if LOOPBACK_GUARD or TCP_LOOPBACK_GUARD:
        expected_scope = (f"loopback-127.0.0.1:{LOOPBACK_PORT}" if TCP_LOOPBACK_GUARD else
                          f"udp-127.0.0.1:{LOOPBACK_PORT}")
        expected_filters = 6 if TCP_LOOPBACK_GUARD else 8
        if (ready.get("scope") != expected_scope or len(ready.get("filter_ids", [])) != expected_filters
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
    if CBUF_COMMAND:
        threading.Thread(target=_cbuf_injector, args=(self, CBUF_COMMAND),
                         name="cbuf-command", daemon=True).start()
    if TRANSPORT_CONNECT:
        threading.Thread(target=_transport_connect_injector, args=(self,),
                         name="transport-connect", daemon=True).start()
    if RING_PROBE:
        threading.Thread(target=_ring_probe_injector, args=(self,),
                         name="ring-probe", daemon=True).start()
    if INJECT_CHALLENGE or GAMESTATE_PATH:
        threading.Thread(target=_inject_challenge_response, args=(self,),
                         name="inject-challenge", daemon=True).start()
    if CALL_CHALLENGE_PARSER:
        threading.Thread(target=_call_challenge_parser, args=(self,),
                         name="call-challenge-parser", daemon=True).start()
    if INIT_TRANSPORT:
        threading.Thread(target=_init_transport, args=(self,),
                         name="init-transport", daemon=True).start()
    if CALL_CHALLENGE_BRANCH:
        threading.Thread(target=_call_challenge_branch, args=(self,),
                         name="call-challenge-branch", daemon=True).start()
    if REMOTE_UDP_SEND:
        threading.Thread(target=_remote_udp_send, args=(self,),
                         name="remote-udp", daemon=True).start()
    if REMOTE_UDP_CONNECT:
        threading.Thread(target=_remote_udp_connect, args=(self,),
                         name="remote-udp-connect", daemon=True).start()
    if REMOTE_NETOBJ:
        threading.Thread(target=_remote_netobj, args=(self,),
                         name="remote-netobj", daemon=True).start()


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
_MAP_DIR = os.environ.get("CODOL_MAP_DIR")


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

    # 可选：把额外解出的 gfx 贴图补进 stage 的 main/images 与 hires/images。
    # 阶段 8 文件追踪显示客户端会直接搜索 hires/images/*.iwi，而五包 loose
    # 资源只覆盖 main/images；CODOL_EXTRA_GFX 用分号分隔若干根目录。
    extra_gfx = [Path(p) for p in os.environ.get("CODOL_EXTRA_GFX", "").split(";") if p]
    if extra_gfx:
        staged_gfx = {"hires": 0, "main": 0}
        destination_root = stage / "hires"
        if stage.is_junction() or stage.is_symlink():
            raise ValueError("refusing to stage extra gfx through a shared mount")
        if destination_root.exists() and (destination_root.is_junction() or destination_root.is_symlink()):
            raise ValueError("refusing to write extra gfx through a shared mount")
        for root in extra_gfx:
            # The client searches hires/ first; stage/main is the shared
            # overlay mount, so every extra image/sound goes into the private
            # hires tree (hi-resolution copies first, main copies fill gaps).
            for kind in ("hires", "main"):
                source_kind = root / kind
                if not source_kind.is_dir():
                    continue
                for source in source_kind.rglob("*"):
                    if not source.is_file():
                        continue
                    relative = source.relative_to(source_kind)
                    destination = destination_root / relative
                    if destination.exists():
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    staged_gfx[kind] += 1
        log["extra_gfx"] = staged_gfx
        print("[patched] staged extra gfx:", staged_gfx, flush=True)

    if LOCAL_AUTH_LSG:
        config = b"127.0.0.1 28969\r\n127.0.0.1 28969\r\n03EA\r\n"
        (stage / "dwauth.ini").write_bytes(config)
        ca_path = Path(__file__).resolve().parents[1] / "runs/20261020-live-derived01/tls/ca.crt"
        ca = ca_path.read_bytes()
        bundle = stage / "cacert.pem"
        original = bundle.read_bytes() if bundle.is_file() else b""
        bundle.write_bytes(original + b"\n" + ca)
        log["local_auth_lsg"] = {
            "dwauth_sha256": hashlib.sha256(config).hexdigest(),
            "ca_sha256": hashlib.sha256(ca).hexdigest(),
            "runtime_only": True,
            "port": 28969,
        }
        print("[patched] staged private Auth/LSG config on 127.0.0.1:28969", flush=True)

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

    if MAP_GAMETYPE_FF:
        source_dir = Path(__file__).resolve().parents[1] / "runs/20261022-gametype-ff-v461"
        expected_files = {
            "common_gametype_mp.ff": "13e7ec159501c5e20796b058fe56491fca14117f3d291b0f9f27e5bc050e7be8",
            "localized_common_gametype_mp.ff": "1698ca866e8e711bd7306cbfa856368c6dae60d7b707b0ef38428c07e90e7006",
        }
        destination_dir = stage / "client_shipretail/chinese"
        if destination_dir.is_junction() or destination_dir.is_symlink():
            raise ValueError("refusing to stage gametype FF through a shared mount")
        destination_dir.mkdir(parents=True, exist_ok=True)
        gametype_staged = []
        for name, expected in expected_files.items():
            source = source_dir / name
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise ValueError(f"same-build gametype FF missing or fingerprint mismatch: {source}")
            destination = destination_dir / name
            shutil.copyfile(source, destination)
            gametype_staged.append({"name": name, "sha256": expected})
        log["map_gametype_ff"] = gametype_staged

    if MAP_LOADSCREEN_PLACEHOLDER:
        # Diagnostic only: use this build's own fallback image to satisfy the
        # map loadscreen lookup without touching the shared image-library mount.
        source = stage / "main/images/default.iwi"
        destination = stage / "devraw_shared/images/loadscreen_mp_crossfire.iwi"
        if not source.is_file():
            raise FileNotFoundError(f"same-build fallback IWI missing: {source}")
        for candidate in (stage, destination.parent.parent, destination.parent):
            if candidate.exists() and (candidate.is_symlink() or candidate.is_junction()):
                raise ValueError(f"refusing to write through a shared mount: {candidate}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError(f"unexpected existing diagnostic IWI: {destination}")
        shutil.copyfile(source, destination)
        log["map_loadscreen_placeholder"] = {
            "source": str(source), "destination": str(destination),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "diagnostic_only": True,
        }

    if MAP_COMPASS_PROBE:
        source = (Path(__file__).resolve().parents[1]
                  / "runs/20261022-crossfire-compass-v461/main/images/compass_map_mp_cross_fire.iwi")
        expected = "d2ceae4461f048d16be8570753e8b7fa09f25e3cda76d306763435ddd9f33a88"
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("same-build compass source missing or fingerprint mismatch")
        destination = stage / "devraw_shared/images/compass_map_mp_cross_fire.iwi"
        for candidate in (stage, destination.parent.parent, destination.parent):
            if candidate.exists() and (candidate.is_symlink() or candidate.is_junction()):
                raise ValueError(f"refusing to write through a shared mount: {candidate}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError(f"unexpected existing compass destination: {destination}")
        shutil.copyfile(source, destination)
        log["map_compass_probe"] = {"destination": str(destination), "sha256": expected}

    loose_packs = []
    if MAP_LOOSE_CROSSFIRE:
        loose_packs.append(("crossfire", "20261022-crossfire-loose-v461",
                            "78c0e517fd854d32b35d32bc8d966b3c57b36721f5b6cfa67e3e72fac928bd67",
                            "c340793c2ea18e6e37cde3b94b9475aa6b7f91bd89c2c111eb54b8b119634386", 538))
    if MAP_LOOSE_GAMETYPE:
        loose_packs.append(("gametype", "20261022-gametype-loose-v461",
                            "c96a9b20470ce8c2c8328ab0f8b4cc6b68fa80fcc16789abbfe33d90cc44466f",
                            "3f27b8b4f6fb9392d7340b8f491c10dc46616b35df4e2f63756bb4e10dae768d", 1037))
    if MAP_LOOSE_CRASH_TROPICAL:
        loose_packs.append(("crash_tropical", "20261022-crash-tropical-loose-v461",
                            "da610e1fab1bc7397c68153092c0b5efcae43716d4d02f0744ad453400312cad",
                            "5605bd43ed2dd5ef5000e4f4ca1de977a350df16ce1a55d23eabf5d1304a2d6d", 1099))
    if MAP_LOOSE_SURVIVAL:
        loose_packs.append(("survival", "20261022-survival-loose-v461",
                            "cae5e92b1e55a510b169656411d038810d7542251b6ca6e38f82b2aedf8c5215",
                            "0f3eb5059e5ac45fe21fe2f37a080f0ef63500ec33c82243defe5a8c6b50e56c", 403))
    if MAP_LOOSE_DMZ:
        loose_packs.append(("dmz", "20261022-dmz-loose-v461",
                            "954b9988954e3a5b119433794812aa8600ef8312235b0f2500a1e8084ed880e0",
                            "161dfe18f6b786c8e9800c8ad6f800dd82149a1fda3793574fbe74ff2e5a68c7", 223))
    for label, folder, expected_receipt, expected_source, expected_count in loose_packs:
        root = Path(__file__).resolve().parents[1] / "runs" / folder
        receipt = root / "receipt.json"
        receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
        if receipt_sha != expected_receipt:
            raise ValueError(f"{label} loose receipt fingerprint mismatch")
        report = json.loads(receipt.read_text(encoding="utf-8"))
        if (report.get("build") != 1649370 or report.get("scope") != "all_main"
                or report.get("source_sha256") != expected_source
                or report.get("decoded") != expected_count or report.get("missing")):
            raise ValueError(f"{label} loose resource receipt mismatch")
        mount = stage / "devraw_shared"
        if stage.is_junction() or stage.is_symlink() or (mount.exists() and (mount.is_junction() or mount.is_symlink())):
            raise ValueError("refusing to write through a shared mount")
        staged_loose = 0
        for item in report["resources"]:
            parts = Path(item["member"]).parts
            if len(parts) < 3 or parts[0].lower() != "main" or ".." in parts:
                raise ValueError(f"invalid {label} loose member path")
            source = root.joinpath(*parts)
            if hashlib.sha256(source.read_bytes()).hexdigest() != item["decoded_sha256"]:
                raise ValueError(f"{label} loose resource fingerprint mismatch: {source}")
            destination = mount.joinpath(*parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.parent.is_junction() or destination.parent.is_symlink() or destination.exists():
                raise ValueError(f"unsafe {label} loose destination: {destination}")
            shutil.copyfile(source, destination)
            staged_loose += 1
        log[f"map_loose_{label}"] = {"count": staged_loose,
                                     "receipt_sha256": receipt_sha,
                                     "destination_root": str(mount)}

    if MAP_SUNFLARE and not MAP_LOOSE_CRASH_TROPICAL:
        root = Path(__file__).resolve().parents[1] / "runs/20261022-crash-tropical-sunflare-v461"
        source = root / "main/images/sun_flare_icbm.iwi"
        receipt = root / "receipt.json"
        expected = "b38240472d19f2397220fe301467f0b2c5f4dfc033639381609b466b2f160a94"
        if (hashlib.sha256(receipt.read_bytes()).hexdigest()
                != "164e3d82afa74fd3f7dc8f5700bbb28e09decd83a7d02def3ccf81a5823ec664"
                or hashlib.sha256(source.read_bytes()).hexdigest() != expected):
            raise ValueError("same-build sunflare fingerprint mismatch")
        destination = stage / "devraw_shared/images/sun_flare_icbm.iwi"
        if destination.exists() or destination.parent.is_junction() or destination.parent.is_symlink():
            raise ValueError("unsafe sunflare destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        log["map_sunflare"] = {"sha256": expected, "destination": str(destination)}

    if _MAP_DIR:
        source_dir = Path(_MAP_DIR)
        destination_dir = stage / "client_shipretail/chinese"
        destination_dir.mkdir(parents=True, exist_ok=True)
        staged_all = []
        for source in sorted(source_dir.glob("*.ff")):
            destination = destination_dir / source.name
            shutil.copyfile(source, destination)
            staged_all.append({"name": source.name, "size": destination.stat().st_size})
        log["map_dir_resources"] = staged_all
        print("[patched] staged map dir:", source_dir, len(staged_all), "files", flush=True)

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
    global MAP_PROBE, MAP_LOADSCREEN_PLACEHOLDER, MAP_COMPASS_PROBE, MAP_LOOSE_CROSSFIRE, MAP_LOOSE_GAMETYPE, MAP_GAMETYPE_FF, MAP_SUNFLARE, MAP_LOOSE_CRASH_TROPICAL, MAP_LOOSE_SURVIVAL, MAP_LOOSE_DMZ, MAP_COMMAND_MODE, ROOM_COMMAND, CBUF_COMMAND, PREFIX_CBUF, LOOPBACK_GUARD, TCP_LOOPBACK_GUARD, LOCAL_AUTH_LSG, LOOPBACK_PORT, MAIN_CALL, MAIN_CALL_ECX, PREWRITES, CONNECTION_ADR_PORT, TRANSPORT_CONNECT, RING_PROBE, HOOK_LOOPBACK, INJECT_CHALLENGE, GAMESTATE_PATH, CALL_CHALLENGE_PARSER, INIT_TRANSPORT, CALL_CHALLENGE_BRANCH, RING_TYPE, RAW_UDP_PATCH, RAW_UDP_BRANCH, BRANCH_NOOP, BRANCH_CAPTURE, BRANCH_SOCKET, BRANCH_SENDTO, REMOTE_UDP_SEND, INJECT_REMOTE_RESPONSE, REMOTE_UDP_CONNECT, REMOTE_NETOBJ
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
    parser.add_argument("--map-loadscreen-placeholder", action="store_true",
                        help="diagnostic: stage this build's default.iwi as the Cross Fire loadscreen")
    parser.add_argument("--map-compass-probe", action="store_true",
                        help="stage verified same-build Cross Fire compass IWI in private runtime")
    parser.add_argument("--map-loose-crossfire", action="store_true",
                        help="stage all 538 verified same-build Cross Fire loose assets")
    parser.add_argument("--map-loose-gametype", action="store_true",
                        help="stage all 1037 verified same-build MP gametype loose assets")
    parser.add_argument("--map-loose-crash-tropical", action="store_true",
                        help="stage 1099 verified same-build loose assets carrying sunflare")
    parser.add_argument("--map-loose-survival", action="store_true",
                        help="stage 403 verified same-build loose assets carrying wavy_nml")
    parser.add_argument("--map-loose-dmz", action="store_true",
                        help="stage 223 verified same-build loose assets carrying barrel_d")
    parser.add_argument("--map-gametype-ff", action="store_true",
                        help="stage the signed v461 common and localized MP gametype fastfiles")
    parser.add_argument("--map-sunflare", action="store_true",
                        help="stage the verified same-build sun_flare_icbm IWI")
    parser.add_argument("--map-command-mode", choices=("startup", "queue", "none"), default="startup")
    parser.add_argument("--audit-breakpoints", action="store_true")
    parser.add_argument("--capture-ui-movie", action="store_true")
    parser.add_argument("--room-command",
                        help="等本地房间有效后，在主线程暂停时把一条 ASCII 控制台命令写入原生命令缓冲")
    parser.add_argument("--cbuf-command",
                        help="主菜单阶段把一条 ASCII 控制台命令追加到原生 Cbuf")
    parser.add_argument("--prefix-cbuf",
                        help="在 BeforeCbuf 断点处给已生成的命令文本补一个前缀，例如 mmstart")
    parser.add_argument("--loopback-guard", action="store_true",
                        help="使用私有 2.6.9.7 loopback guard：仅允许该进程的 UDP 127.0.0.1:28969")
    parser.add_argument("--loopback-tcp-guard", action="store_true",
                        help="使用私有动态 WFP guard：仅允许该进程访问 127.0.0.1:28969（TCP/UDP）")
    parser.add_argument("--local-auth-lsg", action="store_true",
                        help="仅在私有运行副本中配置本地 Auth/LSG 同端口与实验 CA")
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
    parser.add_argument("--transport-connect", action="store_true",
                        help="主线程调用 0x621E50 建传输通道，再调用 0x5C05F0 发 getchallenge")
    parser.add_argument("--ring-probe", action="store_true",
                        help="把连接设为 type=2 loopback，调用 0x5C05F0 并捕获环 A 写入")
    parser.add_argument("--ring-type", type=int, default=2,
                        help="ring-probe 使用的 adr type（2=loopback，4=IP）")
    parser.add_argument("--raw-udp-patch", action="store_true",
                        help="把 0x622040 改成直接 sendto（绕过通道表）")
    parser.add_argument("--raw-udp-branch", action="store_true",
                        help="只替换 0x622040 的无效通道分支为 sendto")
    parser.add_argument("--branch-noop", action="store_true",
                        help="把 0x6221D8 无效分支替换成 noop，验证补丁机制")
    parser.add_argument("--branch-capture", action="store_true",
                        help="把 0x6221D8 替换成只记录 [ebp+...] 参数的 cave")
    parser.add_argument("--branch-socket", action="store_true",
                        help="把 0x6221D8 替换成只调用 socket(2,2,17) 的 cave")
    parser.add_argument("--branch-sendto", action="store_true",
                        help="把 0x6221D8 替换成只调用 sendto(-1,...) 的 cave")
    parser.add_argument("--remote-udp-send", action="store_true",
                        help="在客户端进程内新建远程线程直接 sendto getchallenge")
    parser.add_argument("--inject-remote-response", action="store_true",
                        help="把远程线程收到的应答写入 loopback 接收环")
    parser.add_argument("--remote-udp-connect", action="store_true",
                        help="在客户端进程内用固定源端口完成 getchallenge+connect")
    parser.add_argument("--remote-netobj", action="store_true",
                        help="在客户端进程内构造 0xC7AF2C 网络对象并建 socket")
    parser.add_argument("--hook-loopback", action="store_true",
                        help="在 0x6750A0 安装持久 cave hook（实验性，可能崩溃）")
    parser.add_argument("--inject-challenge", action="store_true",
                        help="向 loopback 接收环注入 challengeResponse")
    parser.add_argument("--inject-gamestate",
                        help="把解码后的 gamestate 二进制注入 loopback 接收环")
    parser.add_argument("--call-challenge-parser", action="store_true",
                        help="主线程直接调用 0x5C0FD0 解析 challengeResponse")
    parser.add_argument("--init-transport", action="store_true",
                        help="用 host+0xC/connection 参数调用 0xBB2C40 初始化传输闸门")
    parser.add_argument("--call-challenge-branch", action="store_true",
                        help="用伪造 EBP 帧直接进入 0x5C1678 challengeResponse 分支")
    known, passthrough = parser.parse_known_args(user_argv)
    MAP_PROBE = known.map_probe
    MAP_LOADSCREEN_PLACEHOLDER = known.map_loadscreen_placeholder
    MAP_COMPASS_PROBE = known.map_compass_probe
    MAP_LOOSE_CROSSFIRE = known.map_loose_crossfire
    MAP_LOOSE_GAMETYPE = known.map_loose_gametype
    MAP_GAMETYPE_FF = known.map_gametype_ff
    MAP_SUNFLARE = known.map_sunflare
    MAP_LOOSE_CRASH_TROPICAL = known.map_loose_crash_tropical
    MAP_LOOSE_SURVIVAL = known.map_loose_survival
    MAP_LOOSE_DMZ = known.map_loose_dmz
    if MAP_LOADSCREEN_PLACEHOLDER and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-loadscreen-placeholder requires --map-probe mp_cross_fire_native")
    if MAP_COMPASS_PROBE and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-compass-probe requires --map-probe mp_cross_fire_native")
    if MAP_LOOSE_CROSSFIRE and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-loose-crossfire requires --map-probe mp_cross_fire_native")
    if MAP_LOOSE_GAMETYPE and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-loose-gametype requires --map-probe mp_cross_fire_native")
    if MAP_GAMETYPE_FF and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-gametype-ff requires --map-probe mp_cross_fire_native")
    if MAP_SUNFLARE and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-sunflare requires --map-probe mp_cross_fire_native")
    if MAP_LOOSE_CRASH_TROPICAL and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-loose-crash-tropical requires --map-probe mp_cross_fire_native")
    if MAP_LOOSE_SURVIVAL and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-loose-survival requires --map-probe mp_cross_fire_native")
    if MAP_LOOSE_DMZ and MAP_PROBE != "mp_cross_fire_native":
        parser.error("--map-loose-dmz requires --map-probe mp_cross_fire_native")
    if MAP_LOOSE_CROSSFIRE and MAP_COMPASS_PROBE:
        parser.error("--map-loose-crossfire already includes the compass IWI")
    if MAP_LOOSE_CROSSFIRE and MAP_LOADSCREEN_PLACEHOLDER:
        parser.error("--map-loose-crossfire already includes the authentic loadscreen IWI")
    MAP_COMMAND_MODE = known.map_command_mode
    ROOM_COMMAND = known.room_command
    CBUF_COMMAND = known.cbuf_command
    PREFIX_CBUF = known.prefix_cbuf
    LOOPBACK_GUARD = known.loopback_guard
    TCP_LOOPBACK_GUARD = known.loopback_tcp_guard
    LOCAL_AUTH_LSG = known.local_auth_lsg
    LOOPBACK_PORT = known.loopback_port
    if LOOPBACK_GUARD and TCP_LOOPBACK_GUARD:
        parser.error("two loopback guards cannot be selected together")
    if TCP_LOOPBACK_GUARD and LOOPBACK_PORT != 28969:
        parser.error("TCP loopback guard is built for port 28969")
    if LOCAL_AUTH_LSG and not TCP_LOOPBACK_GUARD:
        parser.error("--local-auth-lsg requires --loopback-tcp-guard")
    if TCP_LOOPBACK_GUARD and not TCP_LOOPBACK_GUARD_PATH.is_file():
        parser.error(f"missing TCP loopback guard: {TCP_LOOPBACK_GUARD_PATH}")
    MAIN_CALL = known.main_call
    MAIN_CALL_ECX = known.main_call_ecx
    PREWRITES = known.prewrite
    CONNECTION_ADR_PORT = known.connection_adr_port
    TRANSPORT_CONNECT = known.transport_connect
    RING_PROBE = known.ring_probe
    HOOK_LOOPBACK = known.hook_loopback
    INJECT_CHALLENGE = known.inject_challenge
    GAMESTATE_PATH = known.inject_gamestate
    CALL_CHALLENGE_PARSER = known.call_challenge_parser
    INIT_TRANSPORT = known.init_transport
    CALL_CHALLENGE_BRANCH = known.call_challenge_branch
    RING_TYPE = known.ring_type
    RAW_UDP_PATCH = known.raw_udp_patch
    RAW_UDP_BRANCH = known.raw_udp_branch
    BRANCH_NOOP = known.branch_noop
    BRANCH_CAPTURE = known.branch_capture
    BRANCH_SOCKET = known.branch_socket
    BRANCH_SENDTO = known.branch_sendto
    REMOTE_UDP_SEND = known.remote_udp_send
    INJECT_REMOTE_RESPONSE = known.inject_remote_response
    REMOTE_UDP_CONNECT = known.remote_udp_connect
    REMOTE_NETOBJ = known.remote_netobj
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
    reuse_runtime = None
    if "--reuse-runtime" in user:
        index = user.index("--reuse-runtime")
        if index + 1 >= len(user):
            raise SystemExit("--reuse-runtime requires an existing session name")
        reuse_runtime = user[index + 1]
        del user[index:index + 2]
    check_breakpoints(user)
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
        if label == "ConfigstringCompare":
            try:
                registers = row.get("registers", {})
                ebp = int(registers["ebp"], 0)
                incoming = struct.unpack("<I", self.process.read(ebp + 8, 4))[0]
                current = struct.unpack("<I", self.process.read(0x77D8240, 4))[0]
                self.record({"configstring_compare": {"incoming": incoming, "current": current,
                                                       "equal": incoming == current,
                                                       "return_address": hex(struct.unpack("<I", self.process.read(ebp + 4, 4))[0])}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"configstring_compare_error": str(error)})
        if label == "ConfigstringIndexReject":
            try:
                index = int(row.get("registers", {})["edi"], 0)
                kind = self.process.read(0x77D8250 + index, 1)[0]
                neighboring_types = self.process.read(0x77D8250 + index - 32, 65).hex()
                self.record({"configstring_index_reject": {"index": index, "type": kind,
                                                           "type_address": hex(0x77D8250 + index),
                                                           "neighbor_types_start": index - 32,
                                                           "neighbor_types_hex": neighboring_types}})
            except (OSError, ValueError, KeyError, IndexError) as error:
                self.record({"configstring_index_reject_error": str(error)})
        if label == "MapLoading":
            try:
                cursor = struct.unpack("<I", self.process.read(0xC89A48C, 4))[0]
                pool = self.process.read(0xC87A48C, 512)
                rows = []
                for index in range(16):
                    offset = struct.unpack("<I", self.process.read(0xC86DD28 + index * 4, 4))[0]
                    value = None
                    if offset < len(pool):
                        value = pool[offset:].split(b"\0", 1)[0].decode("latin-1")
                    rows.append({"index": index, "offset": offset,
                                 "type": self.process.read(0x77D8250 + index, 1)[0],
                                 "value": value})
                self.record({"map_loading_configstrings": {"pool_cursor": cursor, "slots": rows}})
            except (OSError, ValueError, struct.error) as error:
                self.record({"map_loading_configstrings_error": str(error)})
        if label.startswith("Ent"):
            try:
                registers = row.get("registers", {})
                esi = int(registers["esi"], 0)
                bitpos = 0
                if esi:
                    raw = self.process.read(esi + 0x20, 4)
                    bitpos = struct.unpack("<I", raw)[0]
                ebp = int(registers.get("ebp", "0"), 0)
                mode = -1
                if ebp:
                    raw_mode = self.process.read(ebp - 4, 4)
                    mode = struct.unpack("<I", raw_mode)[0]
                count_raw = self.process.read(0x7859558, 1)
                ids = self.process.read(0x7859358, 12)
                n = getattr(self, "_ent_count", 0)
                if n < 12:
                    self.record({"ent": {"label": label, "bitpos": bitpos,
                                         "mode": mode,
                                         "count": count_raw[0],
                                         "ids": ids.hex(), "n": n}})
                self._ent_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"ent_error": f"{label}: {error}"})
        if label.startswith("IdStore"):
            try:
                registers = row.get("registers", {})
                esi = int(registers["esi"], 0)
                eax = int(registers.get("eax", "0"), 0)
                ebx = int(registers.get("ebx", "0"), 0)
                bitpos = struct.unpack("<I", self.process.read(esi + 0x20, 4))[0] if esi else -1
                n = getattr(self, "_idstore_count", 0)
                if n < 8:
                    self.record({"id_store": {"eax": eax, "bl": ebx & 0xFF,
                                              "bitpos": bitpos, "n": n}})
                self._idstore_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"id_store_error": f"{label}: {error}"})
        if label.startswith("Bits"):
            try:
                registers = row.get("registers", {})
                esi = int(registers["esi"], 0)
                eax = int(registers.get("eax", "0"), 0)
                bitpos = 0
                buf = 0
                if esi:
                    bitpos = struct.unpack("<I", self.process.read(esi + 0x20, 4))[0]
                    buf = struct.unpack("<I", self.process.read(esi + 8, 4))[0]
                n = getattr(self, "_bits_count", 0)
                if n < 14:
                    self.record({"bits": {"esi": hex(esi), "buf": hex(buf),
                                          "bitpos": bitpos, "eax": eax, "n": n}})
                self._bits_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"bits_error": f"{label}: {error}"})
        if label.startswith("Float"):
            try:
                registers = row.get("registers", {})
                edi = int(registers["edi"], 0)
                vals = []
                for off in (0x24, 0x28, 0x2C, 0x10, 0x08):
                    raw = self.process.read(edi + off, 4)
                    vals.append(struct.unpack("<f", raw)[0])
                n = getattr(self, "_float_count", 0)
                if n < 12:
                    self.record({"float": {"edi": hex(edi), "f24": vals[0], "f28": vals[1],
                                           "f2c": vals[2], "o10": vals[3], "o08": vals[4], "n": n}})
                self._float_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"float_error": f"{label}: {error}"})
        if label.startswith("Cursor"):
            try:
                registers = row.get("registers", {})
                esi = int(registers["esi"], 0)
                vals = []
                for off in (0x8, 0xC, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24):
                    raw = self.process.read(esi + off, 4)
                    vals.append(struct.unpack("<I", raw)[0])
                n = getattr(self, "_cursor_count", 0)
                if n < 12:
                    buf = vals[0]
                    raw = self.process.read(buf + 160, 12) if buf else b""
                    self.record({"cursor": {"esi": hex(esi), "b8": hex(vals[0]), "bc": hex(vals[1]),
                                            "b10": vals[2], "b14": vals[3], "b18": vals[4],
                                            "b1c": vals[5], "b20": vals[6], "b24": vals[7],
                                            "bytes160_171": raw.hex(), "n": n}})
                self._cursor_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"cursor_error": f"{label}: {error}"})
        if label.startswith("Gate"):
            try:
                registers = row.get("registers", {})
                edi = int(registers["edi"], 0)
                n = getattr(self, "_gate_count", 0)
                if n < 20:
                    self.record({"gate": {"label": label, "edi": hex(edi), "n": n}})
                self._gate_count = n + 1
            except (OSError, ValueError, KeyError) as error:
                self.record({"gate_error": f"{label}: {error}"})
        if label.startswith("DPath"):
            try:
                n = getattr(self, "_dpath_count", 0)
                if n < 12:
                    self.record({"delta_path": {"n": n}})
                self._dpath_count = n + 1
            except (OSError, ValueError) as error:
                self.record({"dpath_error": f"{label}: {error}"})
        if label.startswith("Delta"):
            try:
                n = getattr(self, "_delta_count", 0)
                if n < 12:
                    self.record({"delta_call": {"n": n}})
                self._delta_count = n + 1
            except (OSError, ValueError) as error:
                self.record({"delta_error": f"{label}: {error}"})
        if label.startswith("Ring"):
            try:
                registers = row.get("registers", {})
                edi = int(registers["edi"], 0)
                ebx = int(registers.get("ebx", "0"), 0)
                ring_idx = 0
                if ebx:
                    raw = self.process.read(ebx + 0xA8DC, 4)
                    ring_idx = struct.unpack("<I", raw)[0]
                n = getattr(self, "_ring_count", 0)
                if n < 20:
                    self.record({"ring": {"label": label, "edi": hex(edi),
                                          "ring_idx": ring_idx, "n": n}})
                self._ring_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"ring_error": f"{label}: {error}"})
        if label.startswith("SnapTrace"):
            try:
                registers = row.get("registers", {})
                message = int(registers["esi"], 0)
                ebp = int(registers["ebp"], 0)
                error, cursor, bit, length = struct.unpack("<4I", b"".join(
                    [self.process.read(message, 4), self.process.read(message + 0x1C, 4),
                     self.process.read(message + 0x20, 4), self.process.read(message + 0x14, 4)]))
                snapshot = {
                    "label": label, "error": error, "cursor": cursor, "bit": bit,
                    "length": length,
                    "flags": struct.unpack("<I", self.process.read(ebp - 0x50, 4))[0],
                    "delta_left": struct.unpack("<i", self.process.read(ebp - 0x44, 4))[0],
                    "valid": struct.unpack("<I", self.process.read(ebp - 0x54, 4))[0],
                }
                for key, offset in (("ctx_3bd0", 0x3BD0), ("ctx_3bd4", 0x3BD4)):
                    try:
                        snapshot[key] = struct.unpack("<I", self.process.read(ebp - offset, 4))[0]
                    except OSError:
                        pass
                for key, offset in (("param_ebp8", 8), ("param_ebp10", 0x10), ("param_ebp14", 0x14)):
                    try:
                        snapshot[key] = struct.unpack("<I", self.process.read(ebp + offset, 4))[0]
                    except OSError:
                        pass
                self.record({"snap_trace": snapshot})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"snap_trace_error": f"{label}: {error}"})
        if label.startswith("InjectEntity"):
            try:
                registers = row.get("registers", {})
                cg = int(registers["edi"], 0)
                base = cg + 0x3B98
                before = self.process.read(base, 0x34)
                self.process.write(base + 0x00, struct.pack("<I", 1))            # eType
                self.process.write(base + 0x18, struct.pack("<3f", 5830.0, -4369.0, -95.0))
                after = self.process.read(base, 0x34)
                self.record({"inject_entity": {"cg": hex(cg), "base": hex(base),
                                               "before_head": before[:0x20].hex(),
                                               "after_head": after[:0x20].hex()}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"inject_entity_error": f"{label}: {error}"})
        if label.startswith("DumpCg"):
            try:
                registers = row.get("registers", {})
                cg = int(registers["edi"], 0)
                data = self.process.read(cg, min(0x20000, 0x20000))
                hits = []
                for off in range(0, len(data) - 12, 4):
                    x, y, z = struct.unpack_from("<3f", data, off)
                    if not all(isinstance(v, float) for v in (x, y, z)):
                        continue
                    if not (100.0 < abs(x) < 20000.0 and 100.0 < abs(y) < 20000.0 and -2000.0 < z < 3000.0):
                        continue
                    hits.append({"offset": hex(off), "value": [round(x, 2), round(y, 2), round(z, 2)]})
                    if len(hits) >= 12:
                        break
                self.record({"dump_cg": {"cg": hex(cg), "size": len(data), "candidates": hits}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"dump_cg_error": f"{label}: {error}"})
        if label.startswith("ClearPsError"):
            try:
                registers = row.get("registers", {})
                edi = int(registers.get("edi", "0"), 0)
                before = struct.unpack("<I", self.process.read(edi, 4))[0]
                self.process.write(edi, struct.pack("<I", 0))
                self.record({"clear_ps_error": {"stream": hex(edi), "before": before}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"clear_ps_error_error": f"{label}: {error}"})
        if label.startswith("FillPs"):
            try:
                registers = row.get("registers", {})
                clc = int(registers.get("ebx", "0"), 0)
                arr = struct.unpack("<I", self.process.read(clc + 0xA900, 4))[0] ^ 0x3613BDA3
                count = struct.unpack("<I", self.process.read(clc + 0x3BA0, 4))[0]
                idx = count % 24
                base = arr + idx * 0x58
                self.process.write(base + 12, struct.pack("<3f", 5830.0, -4369.0, -95.0))
                slots = 1
                self.record({"fill_ps": {"clc": hex(clc), "array": hex(arr), "count": count, "slots": slots}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"fill_ps_error": f"{label}: {error}"})
        if label.startswith("DeltaCall"):
            try:
                registers = row.get("registers", {})
                ebp = int(registers["ebp"], 0)
                esi = int(registers.get("esi", "0"), 0)
                last = struct.unpack("<i", self.process.read(ebp - 4, 4))[0]
                cur = struct.unpack("<i", self.process.read(ebp - 0xc, 4))[0] if True else None
                self.record({"delta_call": {"esi": esi, "last": last}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"delta_call_error": f"{label}: {error}"})
        if label.startswith("PsLoop"):
            try:
                registers = row.get("registers", {})
                ebp = int(registers["ebp"], 0)
                if "Delta" in label:
                    esp = int(registers.get("esp", "0"), 0)
                    stream = struct.unpack("<I", self.process.read(esp + 4, 4))[0]
                else:
                    stream = int(registers.get("edi", "0"), 0)
                bit = None
                if stream:
                    try:
                        bit = struct.unpack("<I", self.process.read(stream + 0x24, 4))[0]
                    except OSError:
                        bit = None
                self.record({"ps_loop": {"at": label, "stream": hex(stream) if stream else None,
                                         "bit": bit}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"ps_loop_error": f"{label}: {error}"})
        if label.startswith("SnapTrace"):
            try:
                registers = row.get("registers", {})
                esp = int(registers["esp"], 0)

                def arg(n: int) -> int:
                    raw = self.process.read(esp + 4 * n, 4)
                    return struct.unpack("<I", raw)[0]

                stream = arg(1)
                history = arg(3)
                count = 0
                if history:
                    raw = self.process.read(history + 0x3BA0, 4)
                    count = struct.unpack("<I", raw)[0]
                n = getattr(self, "_snaptrace_count", 0)
                if n < 16:
                    self.record({"snap_args": {
                        "stream": hex(stream), "history": hex(history),
                        "count_3ba0": count, "n": n}})
                self._snaptrace_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"snap_args_error": f"{label}: {error}"})
        if label.startswith("PsBit"):
            try:
                registers = row.get("registers", {})
                edi = int(registers["edi"], 0)
                n = getattr(self, "_psbit_count", 0)
                if n < 20:
                    self.record({"ps_bit": {"label": label, "edi": hex(edi), "n": n}})
                self._psbit_count = n + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"ps_bit_error": f"{label}: {error}"})
        if label.startswith("Present"):
            try:
                registers = row.get("registers", {})
                edi = int(registers["edi"], 0)
                count = getattr(self, "_present_count", 0)
                if count < 20:
                    self.record({"present_probe": {"edi": hex(edi), "n": count}})
                self._present_count = count + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"present_error": f"{label}: {error}"})
        if label.startswith("Slot"):
            try:
                registers = row.get("registers", {})
                ebp = int(registers["ebp"], 0)
                esi = int(registers["esi"], 0)
                edi = int(registers["edi"], 0)

                def peek(offset: int) -> int:
                    raw = self.process.read(ebp + offset, 4)
                    return struct.unpack("<I", raw)[0]

                count = getattr(self, "_slot_count", 0)
                if count < 40:
                    self.record({"slot": {
                        "slot_d0": peek(-0xD0),
                        "esi": hex(esi),
                        "edi": hex(edi),
                        "count_3ba0": peek(-0xCC),
                        "idx_c8": peek(-0xC8),
                    }})
                self._slot_count = count + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"slot_error": f"{label}: {error}"})
        if label.startswith("Decide"):
            try:
                registers = row.get("registers", {})
                ebp = int(registers["ebp"], 0)

                def peek(offset: int) -> int:
                    raw = self.process.read(ebp + offset, 4)
                    return struct.unpack("<I", raw)[0]

                esi = int(registers["esi"], 0)
                stream_error = struct.unpack("<I", self.process.read(esi, 4))[0]
                self.record({"decide": {
                    "loop_c8": peek(-0xC8),
                    "cur_c4": peek(-0xC4),
                    "slot_d0": peek(-0xD0),
                    "stream_error": stream_error,
                    "struct_3bd0": peek(-0x3BD0),
                    "field_54": peek(-0x54),
                    "field_50": peek(-0x50),
                    "field_34": peek(-0x34),
                    "ctx_3bd4": peek(-0x3BD4),
                }})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"decide_error": f"{label}: {error}"})
        if label.startswith("PsField"):
            try:
                registers = row.get("registers", {})
                ecx = int(registers["ecx"], 0)
                esp = int(registers["esp"], 0)
                args = []
                for step in range(1, 6):
                    raw_arg = self.process.read(esp + 4 * step, 4)
                    args.append(struct.unpack("<I", raw_arg)[0])
                count = getattr(self, "_psfield_count", 0)
                if count < 24:
                    self.record({"ps_field": {"ecx": hex(ecx),
                                              "args": [hex(a) for a in args]}})
                self._psfield_count = count + 1
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"ps_field_error": f"{label}: {error}"})
        if label.startswith("PsBegin"):
            self._in_ps = True
            self.record({"ps_begin": {"bit": row.get("registers", {}).get("ecx")}})
        elif label.startswith("PsEnd"):
            self._in_ps = False
            self.record({"ps_end": {"bit": row.get("registers", {}).get("ecx")}})
        elif label.startswith("PsRead"):
            if getattr(self, "_in_ps", False):
                try:
                    edx = int(row.get("registers", {})["edx"], 0)
                    raw = self.process.read(edx + 0x18, 16)
                    cursor, bit = struct.unpack_from("<II", raw, 4)
                    self.record({"ps_read": {"cursor": cursor, "bit": bit}})
                except (OSError, ValueError, KeyError, struct.error) as error:
                    self.record({"ps_read_error": f"{label}: {error}"})
        if label.startswith("CheckLoader"):
            try:
                registers = row.get("registers", {})
                esi = int(registers["esi"], 0)
                loader = struct.unpack("<I", self.process.read(esi + 0x4F4, 4))[0]
                state_c8 = None
                state_5e8 = None
                if loader:
                    try:
                        state_c8 = struct.unpack("<I", self.process.read(loader + 0xC8, 4))[0]
                        state_5e8 = struct.unpack("<I", self.process.read(loader + 0x5E8, 4))[0]
                    except OSError:
                        pass
                self.record({"check_loader": {"obj": hex(esi), "loader": hex(loader),
                                              "loader_c8": state_c8, "loader_5e8": state_5e8}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"check_loader_error": f"{label}: {error}"})
        if label == "CallSite":
            try:
                esp = int(row.get("registers", {})["esp"], 0)
                raw = self.process.read(esp, 6 * 4)
                args = struct.unpack("<6I", raw)
                self.record({"call_site": {"label": label, "esp": hex(esp),
                                           "args": [hex(value) for value in args]}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"call_site_error": f"{label}: {error}"})
        if label.startswith("ClearStreamError"):
            try:
                esi = int(row.get("registers", {})["esi"], 0)
                before = struct.unpack("<I", self.process.read(esi, 4))[0]
                self.process.write(esi, struct.pack("<I", 0))
                after = struct.unpack("<I", self.process.read(esi, 4))[0]
                self.record({"clear_stream_error": {"esi": hex(esi), "before": before, "after": after}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"clear_stream_error_error": f"{label}: {error}"})
        if label == "SnapshotParse":
            try:
                message = int(row.get("registers", {})["ecx"], 0)
                fields = struct.unpack("<7I", self.process.read(message + 8, 28))
                self.record({"snapshot_parse": {
                    "message": hex(message),
                    "fields_08": [hex(value) for value in fields],
                    "byte_cursor": fields[5], "bit_cursor": fields[6],
                    "head": self.process.read(fields[0] or message + 8, 32).hex()}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"snapshot_parse_error": str(error)})
        if label == "SnapshotAccepted":
            self.record({"snapshot_accepted": {
                "ebx": row.get("registers", {}).get("ebx"),
                "clc": row.get("registers", {}).get("ebx")}})
        if label == "ConfigstringStore":
            try:
                registers = row.get("registers", {})
                index = int(registers["edi"], 0)
                pointer = int(registers["eax"], 0)
                message = int(registers["esi"], 0)
                cursors = struct.unpack("<2I", self.process.read(message + 0x1C, 8))
                self.record({"configstring_store": {
                    "index": index, "string": self.process.cstring(pointer),
                    "byte_cursor": cursors[0], "bit_cursor": cursors[1]}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"configstring_store_error": str(error)})
        if label == "GameNameCheck":
            try:
                registers = row.get("registers", {})
                pointer = int(registers["edx"], 0)
                ebp = int(registers["ebp"], 0)
                snapshot = {
                    "edx": hex(pointer),
                    "string": self.process.cstring(pointer),
                    "slot2_type": self.process.read(0x77D8252, 1)[0],
                    "slot_offsets": [struct.unpack("<I", self.process.read(0xC86DD28 + i * 4, 4))[0]
                                     for i in range(6)],
                    "pool_cursor": struct.unpack("<I", self.process.read(0xC89A48C, 4))[0],
                    "return_address": hex(struct.unpack("<I", self.process.read(ebp + 4, 4))[0]),
                }
                self.record({"game_name_check": snapshot})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"game_name_check_error": str(error)})
        if label == "ConfigstringIndexRead":
            try:
                registers = row.get("registers", {})
                message = int(registers["esi"], 0)
                previous = int(registers["ebx"], 0)
                fields = struct.unpack("<7I", self.process.read(message + 8, 28))
                byte_cursor, bit_cursor = fields[5], fields[6]
                samples = {}
                for key, pointer in (("first", fields[0]), ("second", fields[1])):
                    if pointer:
                        try:
                            samples[key] = self.process.read(pointer + bit_cursor // 8 - 2, 20).hex()
                        except OSError as error:
                            samples[key] = str(error)
                self.record({"configstring_index_read": {"previous": previous,
                                                         "byte_cursor": byte_cursor,
                                                         "bit_cursor": bit_cursor,
                                                         "fields_08_to_20": [hex(value) for value in fields],
                                                         "samples_around_bit_cursor": samples}})
            except (OSError, ValueError, KeyError, struct.error) as error:
                self.record({"configstring_index_read_error": str(error)})
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

    # 强杀/异常退出后，私有档案的 currentCharacterIndex 与游戏内缓存可能暂时
    # 不一致；host 在异常处理的档案检查里会因此终止客户端。这里只记录并
    # 跳过该库存 UI 检查，避免因此阻断连接实验（档案数据本身不改）。
    original_observe_state = bridge_mod.GameSessionBridge.observe_state

    def tolerant_observe_state(self):
        try:
            return original_observe_state(self)
        except ValueError as error:
            message = str(error)
            if "selected-character cache" in message or "inventory" in message:
                self.record({"local_profile_warning": message})
                return None
            raise

    bridge_mod.GameSessionBridge.observe_state = tolerant_observe_state

    original_handle_exception = bridge_mod.GameSessionBridge.handle_exception

    def tolerant_handle_exception(self, event, code, address, row):
        # Record the exception code and faulting address (both plain integers so
        # they stay JSON-serialisable).  `event` is an EVENT object and must not
        # be stored directly.
        try:
            self.record({"exception_seen": {"code": int(code),
                                            "address": int(address)}})
        except Exception:  # noqa: BLE001 - diagnostics must never block
            pass
        try:
            return original_handle_exception(self, event, code, address, row)
        except ValueError as error:
            message = str(error)
            if "selected-character cache" in message:
                # The forced stop of an earlier run left the native
                # selected-character cache at 0 while the account profile
                # still names a character.  Restore the cache from the
                # profile so the inventory/UI bridge can finish instead of
                # merely skipping the check (skipping leaves the lobby
                # modes disabled).
                try:
                    from codol_rebuild.adapters.game.profile_format.fields import Fields
                    fields = Fields(self.profiles.schemas["public"])
                    public = self.profiles.account["profiles"]["public"]
                    selected = fields.read(public, "currentCharacterIndex")
                    expected = fields.read(public, f"characterClasses.{selected}.slots.0")
                    repaired = 0
                    if expected and expected > 0:
                        for trap_address, (profile_data, phase, pool) in self.profile_traps.items():
                            self.process.write(profile_data + 68, struct.pack("<I", expected))
                            repaired += 1
                    self.record({"local_profile_repair": {"selected": selected,
                                                          "expected": expected,
                                                          "traps": repaired}})
                    if repaired:
                        return original_handle_exception(self, event, code, address, row)
                except Exception as repair_error:  # noqa: BLE001
                    self.record({"local_profile_repair_error": str(repair_error)})
            if "selected-character cache" in message or "inventory" in message:
                self.record({"local_profile_warning": message})
                return None
            raise

    bridge_mod.GameSessionBridge.handle_exception = tolerant_handle_exception
    if MAP_PROBE and MAP_COMMAND_MODE == "queue":
        menu_queue_mod.COMMAND = ("\nswitchtomainmenu\ndevmap " + MAP_PROBE + "\n").encode("ascii")
        print("[patched] map probe queued after main-menu transition:", MAP_PROBE, flush=True)
    print("[patched] host arguments:", " ".join(host_args), flush=True)
    session_mod.ProcessSession.start = patched_start
    if reuse_runtime:
        import pefile
        from codol_rebuild.adapters.persistence.game_settings import SettingsSession
        root = (COMMUNITY_ROOT / "workspaces" / "offline-runs").resolve()
        previous = (root / reuse_runtime).resolve()
        if previous.parent != root or not previous.is_dir():
            raise SystemExit("--reuse-runtime must name one existing offline-runs session")
        stage = previous / "runtime"
        exe = stage / "codol1649370-offline.exe"
        expected = "141215dd38754d39a45e9b112345049293579006ea98573a0ba51cc4d55ad380"
        if not exe.is_file() or hashlib.sha256(exe.read_bytes()).hexdigest() != expected:
            raise SystemExit("existing runtime executable does not match the verified 1649370 patch set")
        if not (stage / "players").is_dir() or not (stage / "dwauth.ini").is_file():
            raise SystemExit("existing runtime lacks the prepared player or local auth files")

        class ReuseSessionLog(session_mod.SessionLog):
            def __init__(self, runs_root, name):
                if Path(runs_root).resolve() != root:
                    raise ValueError("unexpected runs root")
                self.run_dir = previous / ("reuse-" + __import__("uuid").uuid4().hex[:8])
                self.run_dir.mkdir()
                self.stage = stage
                self.data = {"scope": "offline client runtime reuse", "main_menu_verified": False,
                             "modules": [], "events": [], "started_at": time.time(),
                             "reused_runtime": str(stage)}
                self.phase_started = time.monotonic()
                self.stream = (self.run_dir / "events.jsonl").open("x", encoding="utf-8")

        def reuse_prepare(args, run_dir, actual_stage, log, phase_done):
            if actual_stage.resolve() != stage.resolve() or args.image.resolve() != IMAGE.resolve():
                raise ValueError("runtime or base image changed during reuse")
            settings = SettingsSession(OriginalSettingsStore(SETTINGS_DB), stage / "players")
            log["input_image"] = {"path": str(IMAGE), "sha256": hashlib.sha256(IMAGE.read_bytes()).hexdigest()}
            log["runtime_image_sha256"] = expected
            log["arguments"] = args.argument
            phase_done("reused-existing-runtime")
            return {"image": IMAGE, "exe": exe, "pe": pefile.PE(str(IMAGE)),
                    "settings": settings, "supplier": None}

        launch_mod.SessionLog = ReuseSessionLog
        launch_mod.prepare = reuse_prepare
        print("[patched] reusing existing runtime:", stage, flush=True)
    else:
        launch_mod.prepare = patched_prepare
    launch_mod.AccountRepository = lambda _community_path: OriginalAccountRepository(ACCOUNT_DB)
    game_settings_mod.SettingsStore = lambda _community_path: OriginalSettingsStore(SETTINGS_DB)
    return launch_mod.main(host_args)


if __name__ == "__main__":
    raise SystemExit(main())
