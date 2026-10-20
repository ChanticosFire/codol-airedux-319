"""Rewrite LONG-RUN-GOAL.md §9 so M4 states its real precondition and reachability.

Forty rounds of work have established that M4 cannot begin until one manual step is
done, and that several data sources listed in §9.3 are not obtainable. The section is
rewritten to say so, with an alternative acceptance standard for the case where
manual help is unavailable.
"""
from __future__ import annotations

from pathlib import Path

NEW_SECTION = """## 9. M4 长程目标（2026-10-23 起，第 40 轮修订）

M3 已完成（大厅渲染 + 五项判据）。**M4 的目标是让游戏真正可玩**：从大厅进入房间，
再从房间进入对局。聊天明确不做（官方服务，已永久停服）。

### 9.0 前置条件（第 40 轮新增，必须先满足）

**M4 的全部五项判据都要求客户端已经处在真实大厅里。当前它停在
「欢迎来到使命召唤ONLINE…请先取一个代号」页面，无法离开。**

这个阻断已在第 10–39 轮被反复验证，结论如下：

| 尝试 | 结果 |
|---|---|
| 强推 FE 梯 `G1=2` | 到 `G1=3`、`gate=1`，UI 仍停在代号页或空白前端 |
| 写 `[D+0xC]=1`（firstlogin 返回 1） | FE 梯自发 `G1: 0→1`，然后被 `0x730C50` 挡住 |
| 强写 `[lobby+0x1F4]=2` | 触发 `svc71/task3/7/9`，但 10 秒内崩溃（已确认是崩溃源） |
| 打桩 `0x6BBF30` 为 `mov eax,1; ret` | 24 秒后崩溃 |
| 只用 M3 记录的 6 个补丁 | 24 秒后崩溃（9 处 pump 补丁是必需的） |
| 等待 39 / 75 / 90 秒盼 `task9` 自发 | 不发（除非先写 `1F4=2`） |
| 合成键盘输入（SendInput / WM_CHAR） | 文字进不了输入框 |
| 恢复 2021 年原始存档 | 客户端直接崩溃（存档每次保存用不同密钥加密） |

**唯一未尝试且确定可行的路径：由人手动在该页面输入代号并点「继续」。**

### 9.0.1 需要的人工操作

在客户端停在代号页面时：点击输入框 → 键入任意代号 → 点「继续」→ 确认进入大厅。

之后本项目可自动完成的部分：

1. 把 `runtime/client-1604220/players/config_mp.cfg` 备份为 `config_mp.cfg.onboarded`；
2. 在 `auto_lobby.py` 中加入"启动前若存档缺失则从备份恢复"；
3. 重跑完整流程并归档证据。

### 9.0.2 若无法获得人工协助

则 M4 的验收标准改为：

- **M4-A（可交付）**：服务端侧完备——`svc71/task4`/`task9`、`svc21/task5`、
  `svc255/60049`、`svc80/130-133` 的应答帧全部实现并有离线单测覆盖
  （`tools/test_frames.py` 已 17 项全绿）；客户端侧记录一个"每次启动需一次人工
  代号"的启动流程说明。
- **M4-B（不可达）**：原 9.1 的五项判据，标注为阻塞，原因写明是 9.0。

**不以"技术原因"含糊带过。** 若无法人工介入，M4-B 就是做不到，文档如实记录。

### 9.1 完成判据（M4-B，需 9.0 前置）

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

| 阶段 | 内容 | 依赖 | 状态（第 40 轮） |
|---|---|---|---|
| **M4.1 档案与数据** | `svc255/task60049`（playerData）+ `svc80` getBalance | 9.0 | 服务端已实现（`server319/profile.py` + `lsg_derived.py`），客户端未请求过 |
| **M4.2 房间列表** | `svc71/task9` 稳定触发 + `svc21/task5` | 9.0 | 应答帧已实现且有单测；`task9` 仅在强写 `1F4=2` 时出现过 |
| **M4.3 房间内状态** | `svc71/task3`/`task7` 的语义 | 9.0 + M4.2 | **已查明是崩溃日志上报**（`ClientOffline`/`UserWarning`/`ClientException`），不是房间协议 |
| **M4.4 对局入口** | UDP 游戏通道、地图清单、`svc10` 文件下发 | 9.0 + M4.3 | 未开始；资源不可解包（见 9.3） |

### 9.3 关于「深挖客户端数据」的判断（第 40 轮修订）

**结论：原计划里"从 `.ifs` 提取"的假设是错的，这条路已证伪。**

第 31–35 轮实测：对 987 个 `.ifs` 包做 2 MB 与 6 MB 两档深度扫描，
`rankIconTable`、`weapons_mp`、`.csv`、`attachment` **全部 0 命中**；
整个客户端目录下不存在任何 `*.csv`。

而主程序里有这些路径（VA `0xABDE33`）：

```
mp/callsignTitle.csv   mp/rankIconTable.csv   mp/callsignBackground.csv
mp/callsignIcon.csv    mp/callsignFrame.csv
```

即它们是**运行期从 fastfile 按名加载**的资源，不是 `.ifs` 容器里的独立文件。
fastfile 加密（`IWff0100` 头后从 `0x14` 起高熵），**无法离线提取**。

| 数据 | 原计划的获取方式 | 实际状态 |
|---|---|---|
| `mp_playlists_*` | `.ifs` 提取 | 已提取出 `mp_playlists.ff`（49493 B），但内容加密，**不可读** |
| `rankIconTable.csv` | 客户端资源 | **不可提取**，只能运行期由客户端加载 |
| 武器/配件表 | 客户端 `.ifs` | **不可提取**，同上 |

因此 M4 的资源前置条件**无法通过解包满足**。要么让客户端自己加载（需先进大厅），
要么放弃这部分（房间列表的渲染可能不依赖它，取决于 UI 实现）。

### 9.4 每轮循环（沿用）

1. 从队列取一项，做最小可验证增量；
2. 跑一次实机，留下 `runs/<id>/` 证据；
3. 更新 `PROJECT_STATUS.md` 与 `MILESTONES.md`，阴性结果也要写；
4. 本地提交，推送；
5. 同一阻断连续 3 轮无进展则换方向。

### 9.5 当前队列（第 40 轮重写）

**最高优先：等待 9.0 的人工操作。** 在此之前，可做的工作限于服务端侧与文档：

1. **补齐服务端回归测试**——把 `svc71/task4`、`task9`、`svc21/task5`、
   `svc255/60049`、`svc80/130-133` 的应答接进 `tools/test_frames.py` 的契约测试；
2. **整理机制说明**——把第 12.36–12.57 节的 `0xBAD800` 状态机全图、
   容器查找契约、`[D+0xC]` 与 FE 梯的关系写成可供他人复用的技术文档；
3. **`MILESTONES.md` 同步 9.0**——把"需人工一步"写在最显眼的位置。

**明确不再做**：内存强推类实验（`1F4`、`G1`、`FE_state`、打桩）——
它们要么无效要么崩溃，已各有明确记录；线程上下文采样（位数不匹配，已放弃）。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    path = root / "LONG-RUN-GOAL.md"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## 9."):
            start = i
            break
    if start is None:
        print("section 9 not found")
        return
    head = "\n".join(lines[:start])
    path.write_text(head.rstrip("\n") + "\n\n" + NEW_SECTION, encoding="utf-8")
    print(f"§9 rewritten: {len(lines)} lines -> {len(path.read_text(encoding='utf-8').splitlines())} lines")


if __name__ == "__main__":
    main()
