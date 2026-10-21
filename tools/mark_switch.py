"""Mark the 1604220 -> 1649370 main-line switch across the existing documents.

Adds a short banner at the top of PROJECT_STATUS.md, HANDOFF-CURRENT.md and MILESTONES.md that says
what is current, what is archived, and where the two new documents are. Nothing is deleted - the
1604220 records stay exactly where they are and remain the reference for that build.
"""
from pathlib import Path

ROOT = Path("E:/GAME/COD/codol-airedux/319")

BANNER_STATUS = """
> ## 主线已切换（2026-10-21）
>
> **当前主线是 Build 1649370，目标是做出 bot 对战。**
> 入口文档：[1649370-STATUS.md](1649370-STATUS.md)。
>
> **1604220 的全部研究已归档但完整保留**：[ARCHIVE-1604220.md](ARCHIVE-1604220.md)
> 是索引与提炼，本文件 §0 与 §12.x 是逐轮原始记录，两者都有效。
>
> 切换原因：1604220 的 M4 卡在"收包 socket 队列始终为空"，
> 把句柄映射到端口需要系统级手段（已记为 blocked）；
> 而 1649370 有社区完整实现（明文 Fastfile、PE 恢复镜像、运行时补丁、本地档案），
> 且**不走网络**，绕开了 1604220 的卡点。
>
> 1604220 中可直接复用的三项：**服务端栈**（40 项测试全绿）、
> **pump 状态机逆向**（同引擎、结构大概率同构）、**方法论与工具集**。
>
"""

BANNER_HANDOFF = """
> ## 主线已切换（2026-10-21）
>
> **当前主线：Build 1649370，目标 bot 对战。**
> 先读 [1649370-STATUS.md](1649370-STATUS.md)。
>
> **1604220 的交接内容原样保留**（本文件 §14 起与 §16 系列），
> 提炼索引见 [ARCHIVE-1604220.md](ARCHIVE-1604220.md)。
> 两个版本的共同前提（TLS 自签、Auth 七字段、LSG 派生）在任何版本上都适用。
>
> **注意**：本文件描述的 1604220 启动链（`tools/run_verified.ps1`）
> 只服务 1604220；1649370 用 `tools/launch_1649370.py`。
>
"""

MILESTONE_ROW = """| **主线切换（→ 1649370）** | **完成** | 2026-10-21 主线切到 Build **1649370**，目标是 **bot 对战**。入口 [1649370-STATUS.md](1649370-STATUS.md)；1604220 成果归档于 [ARCHIVE-1604220.md](ARCHIVE-1604220.md)。已打通：社区包指纹校验 `ready:true`、`--prepare-only` 资源准备、**Fastfile 解密**（`decode_fastfile` 用原版 EXE material@`0x6984B0` 解出 `mp_playlists.zone` 26,115 字节，签名验证通过）、**绕过 `CreateProcessAsUserW` 的 WinError 1346**（`tools/launch_1649370.py` 用 `CreateProcessW` 替换，保留 host 断点桩）。当前卡点：`0xC4A7A1` 访问违例（`cmp byte [eax],0`，`eax=8`，`strnlen` 类循环用了无效指针），待用完整 `--resource-library`/`--loose-library` 参数重试 |
"""


def patch(path: Path, anchor: str, banner: str, before: bool = True) -> None:
    text = path.read_text(encoding="utf-8")
    if "主线已切换" in text:
        print(f"{path.name}: already patched")
        return
    if anchor not in text:
        print(f"{path.name}: ANCHOR NOT FOUND -> {anchor[:40]!r}")
        return
    if before:
        text = text.replace(anchor, banner + "\n" + anchor, 1)
    else:
        text = text.replace(anchor, anchor + "\n" + banner, 1)
    path.write_text(text, encoding="utf-8")
    print(f"{path.name}: patched")


def main() -> None:
    patch(ROOT / "PROJECT_STATUS.md",
          "---\n\n## 0. 最新结论索引（第 60–188 轮）",
          BANNER_STATUS)

    patch(ROOT / "HANDOFF-CURRENT.md",
          "# 交接文档：CODOL 3.19.26.17 / Build 1604220 离线复活 — 2026-10-26",
          BANNER_HANDOFF, before=False)

    path = ROOT / "MILESTONES.md"
    text = path.read_text(encoding="utf-8")
    if "主线切换（→ 1649370）" in text:
        print("MILESTONES.md: already patched")
    else:
        marker = "| M5 成果整理与协作 |"
        if marker in text:
            text = text.replace(marker, MILESTONE_ROW + marker, 1)
            path.write_text(text, encoding="utf-8")
            print("MILESTONES.md: row added")
        else:
            print("MILESTONES.md: M5 row not found")


if __name__ == "__main__":
    main()
