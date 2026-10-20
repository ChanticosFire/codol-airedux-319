"""Rewrite the M4 row in MILESTONES.md to state the manual precondition up front."""
from __future__ import annotations

from pathlib import Path

ROW = (
    "| M4 玩法与数据 | **阻塞于前置条件（需人工一步）** | "
    "**M4 五项判据全部要求客户端处在真实大厅，而它停在「请先取一个代号」页面无法离开。** "
    "第 10–39 轮已验证并记录九类尝试全部失败（强推 G1、写 `[D+0xC]`、强写 `1F4=2`、"
    "打桩 `0x6BBF30`、仅用 M3 六补丁、等待自发 `task9`、合成键盘输入、恢复原始存档）——"
    "其中强写 `1F4=2`、打桩、六补丁三项会导致崩溃。"
    "**唯一确定可行路径：人工在该页面输入代号并点「继续」**，之后 config_mp.cfg 可备份复用。"
    "已完成的服务端成果：`server319/profile.py` 档案持久化、`svc80`/`svc255`/`svc71`/`svc21` 应答、"
    "`tools/test_frames.py` 17 项帧契约单测全绿、`svc71` 请求 TLV 结构完全解析、"
    "`svc71/task3`/`task7` 查明为崩溃日志上报而非房间协议。"
    "资源路线已证伪：`rankIconTable.csv` 等在 fastfile 内，加密不可解包。"
    "详见 [LONG-RUN-GOAL.md](LONG-RUN-GOAL.md) §9.0 与 PROJECT_STATUS.md §12.36–§12.57 |"
)


def main() -> None:
    path = Path(r"E:\GAME\COD\codol-airedux\319\MILESTONES.md")
    text = path.read_text(encoding="utf-8")
    start = text.find("| M4 玩法与数据 |")
    if start < 0:
        print("M4 row not found")
        return
    end = text.find("\n", start)
    old = text[start:end]
    path.write_text(text[:start] + ROW + text[end:], encoding="utf-8")
    print(f"M4 row updated ({len(old)} -> {len(ROW)} chars)")


if __name__ == "__main__":
    main()
