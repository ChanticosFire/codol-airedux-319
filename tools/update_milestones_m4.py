"""Update the M4 row in MILESTONES.md to reflect the current blocked state."""
from __future__ import annotations

from pathlib import Path

ROW = (
    "| M4 玩法与数据 | **受阻（需人工一步）** | 第 23 轮状态：补丁、协议、坐标均已排除，"
    "阻断收敛为「客户端存档缺少已建档状态」——`[D+0xC]=0` 使 firstlogin 返回 0，FE 梯不前进。"
    "已验证的阴性结论：强推 G1 停在代号页或空白前端；强推 `[lobby+0x1F4]=2` 崩溃；"
    "打桩 `0x6BBF30` 24 秒后崩溃；等 90 秒仍无 `svc71/task9`；fastfile 资源不可解包；"
    "社区脚本缺 6 个依赖模块。**需要人工完成一次代号流程**并备份 config_mp.cfg。"
    "已完成的服务端成果：`server319/profile.py` 档案持久化、`svc80`/`svc255` 应答、"
    "`tools/test_frames.py` 17 项帧结构单测全绿。详见 PROJECT_STATUS.md §12.36-§12.39 |"
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
