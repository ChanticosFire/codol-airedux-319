"""Correct every document that still recommends sending a large record on UDP 3074.

Rounds 193 and 195 tested that idea directly: a 160-byte reply on the probe, and a 160-byte datagram to every UDP port the
client owns, from two source ports each. Neither produced any change. So the recommendation written into four documents is
wrong and has to be replaced everywhere, together with a clear statement of what is actually known and what remains unknown.
"""
from pathlib import Path

ROOT = Path("E:/GAME/COD/codol-airedux/319")

ONE_LINER_OLD = "**服务端必须返回 ≥136 字节、且能通过两个过滤的记录，这条链才可能往下走。**"
ONE_LINER_NEW = (
    "**数据不足是必要条件但不充分**：第 193/195 轮已实测——回 160 字节给探测包源、\n"
    "以及向客户端全部 6 个 UDP 端口各发 160 字节，状态都毫无变化。\n"
    "**所以真正未解决的是通道：`vt+0x1C` 的收包读不到我们发的任何字节。**"
)

RULED_OUT_OLD = "**发 9 字节类型 `0x15` 消息到 UDP 3074**（状态变 5，但那是自发流程，非消息导致）。"
RULED_OUT_NEW = (
    "**发 9 字节类型 `0x15` 消息到 UDP 3074**（状态变 5，但那是自发流程，非消息导致）、\n"
    "**回 160 字节记录到探测包源 `22011`**（§12.204，无任何变化）、\n"
    "**向客户端全部 6 个 UDP 端口从 2 个源端口各发 160 字节**（§12.206，无任何变化）。"
)

M4_OLD = "**服务端下一步：在 UDP 3074 上返回 ≥136 字节、且能通过两个过滤（条目不重复 + 追加成功）的记录。**"
M4_NEW = (
    "**通道尚未定位**：§12.204 证明回探测包源无效，§12.206 证明向全部 6 个 UDP 端口发也无效，"
    "所以 `vt+0x1C`（`0xC73FB0`）的收包究竟读哪个 socket 仍未知。"
    "**下一步应先确认该收包是否被调用、是否首步即返回 0**（哨兵法挂 `0xC73FB0` 入口）。"
)

MACHINE_OLD = (
    "**下一轮该做什么**：先弄清 `0xBC1D20` 期望的 136 字节记录**具体字段布局**\n"
    "（反汇编 `0xB770F0`、`0xB75720` 的组合），然后在 `lobby_udp.py` 里\n"
    "构造一条能通过 `Add` 两个过滤的记录，观察状态是否自然变成 2。"
)
MACHINE_NEW = (
    "**先解决通道，再谈数据**。第 193/195 轮的实验已经说明：即使发 160 字节，\n"
    "`vt+0x1C` 也读不到（§12.204、§12.206）。\n"
    "\n"
    "**建议的第一步**：在 `0xC73FB0` 入口挂哨兵（`tools/probe_reg.py`），确认三件事——\n"
    "① 它每帧是否真的被调用；② 被调用时的 `ecx` 与参数；③ 它是否在第一步就返回 0。\n"
    "\n"
    "**这能区分「没收到数据」与「收到了但不合格」**——这是当前最关键的一分为二。\n"
    "\n"
    "**若确认它从未收到数据**，则方向转为：业务数据可能走 **TCP 4174（LSG 通道）**，\n"
    "因为 §12.205 实测客户端只有一条 TCP 连接 `127.0.0.1:4351 → 127.0.0.1:4174`，\n"
    "而 UDP 侧 6 个端点都已被排除。"
)

HANDOFF_OLD = (
    "> **在 UDP 3074 上返回 ≥136 字节、且能通过 `Add` 两个过滤的记录。**\n"
    "> 两个过滤是 `0xBBA465`（条目重复检查）与 `0xBBA483`（追加成功检查），\n"
    "> 都跳向 `0xBBA5A5`（跳过写 2）。"
)
HANDOFF_NEW = (
    "> **先解决通道，再谈数据。**\n"
    ">\n"
    "> 第 193/195 轮的实验已经否定了「多发点数据就行」这条路：回 160 字节给探测包源、\n"
    "> 以及向客户端全部 6 个 UDP 端口各发 160 字节，状态都毫无变化。\n"
    "> **所以 `vt+0x1C`（`0xC73FB0`）的收包读不到我们发的任何字节。**\n"
    ">\n"
    "> **建议的第一步**：在 `0xC73FB0` 入口挂哨兵，确认它是否被调用、参数是什么、\n"
    "> 以及是否首步即返回 0。这能区分「没收到数据」与「收到了但不合格」。\n"
    ">\n"
    "> **若确认从未收到数据**：业务数据可能走 **TCP 4174（LSG 通道）**——\n"
    "> 客户端只有这一条 TCP 连接，而 UDP 侧 6 个端点已被全部排除。"
)

EDITS = [
    ("PROJECT_STATUS.md", ONE_LINER_OLD, ONE_LINER_NEW),
    ("PROJECT_STATUS.md", RULED_OUT_OLD, RULED_OUT_NEW),
    ("MILESTONES.md", M4_OLD, M4_NEW),
    ("PUMP-STATE-MACHINE.md", MACHINE_OLD, MACHINE_NEW),
    ("HANDOFF-CURRENT.md", HANDOFF_OLD, HANDOFF_NEW),
]


def main() -> None:
    for name, old, new in EDITS:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        if old not in text:
            print(f"{name}: PATTERN NOT FOUND - skipped")
            continue
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        print(f"{name}: corrected")


if __name__ == "__main__":
    main()
