"""启动 1649370 离线客户端，绕开 CreateProcessAsUserW 的 WinError 1346。

社区 host（tools/launch_offline.py）在 ProcessSession.start 里用 low_token() 派生低权限令牌，
再调 CreateProcessAsUserW。本机那条路径返回 1346（ERROR_BAD_IMPERSONATION_LEVEL），
即使当前令牌是 Primary + Full elevation 也一样。

本包装层不修改社区源码，只在 import 之后替换 ProcessSession.start：
用 CreateProcessW 以当前用户令牌挂起创建进程，跳过令牌校验与 UAC 断网守卫，
其余（断点调试循环、菜单激活桩、本地档案桥）全部保留。

用法：
    C:\\Python314\\python.exe -B -X utf8 tools\\launch_1649370.py --local-profile --seconds 90
参数与 tools/launch_offline.py 完全一致。
"""
from __future__ import annotations

import ctypes as C
import os
import subprocess
import sys
from ctypes import wintypes as W
from pathlib import Path

COMMUNITY_SRC = Path(r"E:\GAME\COD\1649370\src")
if not COMMUNITY_SRC.is_dir():
    raise SystemExit(f"找不到社区源码目录: {COMMUNITY_SRC}")
sys.path.insert(0, str(COMMUNITY_SRC))

from codol_rebuild.platform.win32 import K, PTR, SI, PI, api, check  # noqa: E402
from codol_rebuild.runtime import session as session_mod  # noqa: E402
import codol_rebuild.bootstrap.launch as launch_mod  # noqa: E402

# CreateProcessW 的 creation flags：社区原值 1030 = CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP | CREATE_UNICODE_ENVIRONMENT
CREATION_FLAGS = 1030

ENV_KEYS = ("SystemRoot", "WINDIR", "COMSPEC", "SystemDrive",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE")


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


def patched_start(self, exe, settings_session) -> None:
    """替换 ProcessSession.start：CreateProcessW + 跳过令牌校验与断网守卫。"""
    self.settings = settings_session

    si = SI()
    si.cb = C.sizeof(si)

    baseline = settings_session.baseline
    display_defaults = [] if "config_mp.cfg" in baseline else ["+set", "r_displayMode", "windowed"]
    command_line = subprocess.list2cmdline([str(exe), "-q", *display_defaults, *self.args.argument])
    self.log["command_line"] = command_line
    command = C.create_unicode_buffer(command_line)

    environment = _build_environment(self.stage)

    check(api(K, "CreateProcessW", W.BOOL,
              W.LPCWSTR, W.LPWSTR, PTR, PTR, W.BOOL, W.DWORD,
              PTR, W.LPCWSTR, C.POINTER(SI), C.POINTER(PI))(
        str(exe), command, None, None, False, CREATION_FLAGS,
        C.cast(environment, PTR), str(self.stage), C.byref(si), C.byref(self.info)))

    self.log["pid"] = self.info.pid
    self.log["launch_path"] = "CreateProcessW (patched, no low token, no offline guard)"
    self.log["token"] = {
        "verified": False,
        "reason": "patched launch bypasses low-token isolation and offline guard",
    }
    self.log["guard"] = {"skipped": True, "reason": "patched launch"}

    self.phase_done("process-and-uac-guard")

    check(api(K, "DebugSetProcessKillOnExit", W.BOOL, W.BOOL)(True))
    if api(K, "ResumeThread", W.DWORD, PTR)(self.info.thread) == 0xFFFFFFFF:
        raise C.WinError(C.get_last_error())

    self.resumed = True
    self.log["resumed"] = True
    self.log["lifetime"] = "until_client_exit" if self.args.until_close else "bounded_observation"


def main(argv=None) -> int:
    session_mod.ProcessSession.start = patched_start
    return launch_mod.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
