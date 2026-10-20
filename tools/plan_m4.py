"""Plan M4: rewrite the long-run goal criteria and break M4 into stages."""
from pathlib import Path

GOAL = """
---

## 9. M4 长程目标（2026-10-23 起）

M3 已完成（大厅渲染 + 五项判据）。**M4 的目标是让游戏真正可玩**：从大厅进入房间，
再从房间进入对局。聊天明确不做（官方服务，已永久停服）。

### 9.1 完成判据（M4 验收）

按顺序达成，前一项不通过不进入下一项：

| # | 判据 | 可验证证据 |
|---|---|---|
| 1 | **玩家档案生效** | 重登后服务端持有同一 `user_id` 的 playerData；客户端不再要求选人/键位 |
| 2 | **房间列表可见** | 大厅「多人竞技」页出现至少一个可点房间条目（截图 + `svc71/task9` 应答字节） |
| 3 | **可建房/加入** | 点击后进入房间界面，能看到房名/玩家槽位（截图 + 对应 service 请求/应答） |
| 4 | **开始对局** | 房间内点开始 → 加载地图 → 进入游戏内（截图 + UDP 会话建立记录） |
| 5 | **对局可退出** | 一局结束后回到大厅，状态不残留（日志 + 截图） |

第 4 项是本阶段最重的，涉及 UDP 游戏通道；不要求打完一局，只要求**进入游戏内**。

### 9.2 阶段拆分（协议优先）

| 阶段 | 内容 | 依赖 | 预估权重 |
|---|---|---|---|
| **M4.1 档案与数据** | `svc255/task60049`（playerData：level/wallet/entitlements）+ `svc80` getBalance（task 130–133）落地为服务端应答 | 无 | 小 |
| **M4.2 房间列表** | 先让 `svc71/task9`（FindSessions）稳定触发，再回 114B bdMatchMaking 条目；补 `svc21/task5`（含 tag `0x0A`） | M4.1 | 中 |
| **M4.3 房间内状态** | `svc71/task3`/`task7` 的语义与应答；玩家槽位、房主权限 | M4.2 | 中 |
| **M4.4 对局入口** | UDP 游戏通道（3074/3076 之外的会话端口）、地图清单 `mp_playlists_*.info` 的提供、`svc10` 文件下发 | M4.3 + 资源表 | 大 |

### 9.3 关于「深挖客户端数据」的判断

**结论：做最小集，不做全面挖掘。**

需要的（按 M4 阶段）：

| 数据 | 用途 | 何时需要 | 获取方式 |
|---|---|---|---|
| `mp_playlists_shipRetail_release.info`（139206B） | 地图/模式清单，房间列表和匹配都依赖 | M4.2 之后 | 客户端 `main/` 下的 `.ifs` 提取；社区已确认请求名与大小 |
| `rankIconTable.csv` | 等级图标（否则生涯页军衔显示异常） | M4.1 之后 | 客户端资源 |
| 武器/配件表 | 仅 M4.3 房间内展示需要 | M4.3 | 客户端 `.ifs` |

**不需要的**：全量 `.ifs` 解包、材质/音频、本地化文本。这些对「能进对局」没有直接贡献，
投入产出比低。等真正卡在某个资源缺失时再单项提取。

### 9.4 每轮循环（沿用）

1. 从队列取一项，做最小可验证增量；
2. 跑一次实机（`runs/run_1604220.ps1` 或内联命令），留下 `runs/<id>/` 证据；
3. 更新 `PROJECT_STATUS.md` 与 `MILESTONES.md`，阴性结果也要写；
4. 本地提交，推送；
5. 同一阻断连续 3 轮无进展则换方向。

### 9.5 当前队列（从 M4.1 起）

1. **验证 onboarded 是否被覆盖**——跑的时候中途读 `0xDC3EA0`，决定是「写太晚」还是「被回滚」。
   若是回滚，则放弃内存路线，改走协议。
2. **落地 svc255 playerData / svc80 getBalance**——把 `svc80_data/playerdata.json`
   与 `bdsvc319` 的 `60049`、`130-133` 形状接进 `lsg_derived.py`，观察客户端是否消费。
3. **追 `svc71/task9` 的触发条件**——它在部分 run 出现、部分不出现，先弄清触发条件
   再谈应答。
4. **提取 `mp_playlists_shipRetail_release.info`**——房间列表的前置数据。
"""

MILESTONE_ROWS = {
    "M4 玩法与数据": (
        "| M4 玩法与数据 | 进行中 | **已拆为 4 个子阶段**（见 [LONG-RUN-GOAL.md](LONG-RUN-GOAL.md) §9.2）："
        "M4.1 档案与数据（svc255/task60049 + svc80 getBalance）→ M4.2 房间列表（svc71/task9 + svc21/task5）"
        "→ M4.3 房间内状态（svc71/task3/7）→ M4.4 对局入口（UDP 通道 + mp_playlists）。"
        "验收判据五条见 §9.1。**聊天明确不做**（官方服务已永久停服）。"
        "资源表只做最小集：`mp_playlists_*`、`rankIconTable.csv`、武器/配件表，不做全量 .ifs 解包 |"
    ),
}


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")

    goal = root / "LONG-RUN-GOAL.md"
    text = goal.read_text(encoding="utf-8")
    if "## 9. M4 长程目标" not in text:
        text += GOAL
        goal.write_text(text, encoding="utf-8")
        print("LONG-RUN-GOAL.md: M4 section added")
    else:
        print("LONG-RUN-GOAL.md: already has M4")

    ms = root / "MILESTONES.md"
    text = ms.read_text(encoding="utf-8")
    for old_prefix, new_row in MILESTONE_ROWS.items():
        for line in text.splitlines():
            if line.startswith("| " + old_prefix + " |"):
                text = text.replace(line, new_row, 1)
                print("MILESTONES.md: rewrote", old_prefix)
                break
        else:
            print("MILESTONES.md: row not found:", old_prefix)
    ms.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
