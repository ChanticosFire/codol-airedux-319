"""启动 1649370 离线客户端，绕开 CreateProcessAsUserW 的 WinError 1346。

社区 host（src/codol_rebuild/bootstrap/launch.py）在 ProcessSession.start 里用 low_token()
派生低权限令牌再调 CreateProcessAsUserW；本机那条路径返回 1346
（ERROR_BAD_IMPERSONATION_LEVEL），即使当前令牌是 Primary + Full elevation。

本包装层不修改社区源码，只在 import 之后替换 ProcessSession.start：
用 CreateProcessW 以当前用户令牌挂起创建进程，跳过令牌校验与 UAC 断网守卫。

**关键**：启动参数必须由本文件显式构造。社区的 tools/launch_offline.py 会在
build_plan() 里补上 --image / --patches / --overlay / --queue-main-menu，
而直接调 bootstrap.launch.main 会跳过那一步 —— 结果是没打补丁、没有明文 fastfile、
也没装菜单激活桩，客户端会在 "无法找到 code_pre_gfx_mp" 之类的错误上停住。

用法：
    C:\\Python314\\python.exe -B -X utf8 tools\\launch_1649370.py --seconds 120
    C:\\Python314\\python.exe -B -X utf8 tools\\launch_1649370.py --full --seconds 120
其余社区参数（--prepare-only / --local-profile / --until-close 等）原样透传。
"""
from __future__ import annotations

import argparse
import ctypes as C
import os
import shutil
import subprocess
import sys
from ctypes import wintypes as W
from pathlib import Path

COMMUNITY_ROOT = Path(r"E:\GAME\COD\1649370")
COMMUNITY_SRC = COMMUNITY_ROOT / "src"
if not COMMUNITY_SRC.is_dir():
    raise SystemExit(f"找不到社区源码目录: {COMMUNITY_SRC}")
if not COMMUNITY_ROOT.is_dir():
    raise SystemExit(f"找不到社区项目目录: {COMMUNITY_ROOT}")
sys.path.insert(0, str(COMMUNITY_SRC))

from codol_rebuild.platform.win32 import K, PTR, SI, PI, api, check  # noqa: E402
from codol_rebuild.runtime import session as session_mod  # noqa: E402
from codol_rebuild.adapters.game.v1649370.observation_points import BREAKPOINTS  # noqa: E402
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
# 环境变量 CODOL_FSCHECK_BYTES 可切换内容形态：
#   empty  -> 0 字节        comment -> 社区那 77 字节注释
#   newline-> 单个换行      probe   -> 用 0x4F5120 打开的那个名字当占位
_FS_CHECK_MODE = os.environ.get("CODOL_FSCHECK_BYTES", "empty").lower()
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
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--name")
    parser.add_argument("--full", action="store_true",
                        help="同时挂载 image/loose 资源库（对应社区 start_client.cmd）")
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--until-close", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--local-profile", action="store_true")
    parser.add_argument("--verify-resources", action="store_true")
    known, passthrough = parser.parse_known_args(user_argv)

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
    args += ["--", *GAME_ARGUMENTS]
    return args


def main(argv=None) -> int:
    user = list(sys.argv[1:] if argv is None else argv)
    host_args = build_host_arguments(user)
    print("[patched] host arguments:", " ".join(host_args), flush=True)
    session_mod.ProcessSession.start = patched_start
    launch_mod.prepare = patched_prepare
    return launch_mod.main(host_args)


if __name__ == "__main__":
    raise SystemExit(main())
