"""Record the community-repository survey (M4 planning input)."""
from pathlib import Path

TEXT = """
### 12.19 社区仓库遍历结果（2026-10-23）

按要求 `git fetch --all` 后确认仓库已是最新，无新提交：

```
origin  https://gitea.codolai.win:2096/ember-forge/codol-ember.git
HEAD    28368dd Merge pull request 'docs: curate 2697 reference and 1604220 adoption guidance' (#7)
behind   0
```

#### 结论一：社区自己也没有做到房间与对局

仓库内多处明确写着未实现/未验收：

| 出处 | 原文 |
|---|---|
| `工具-tools/lobby-reproduction1604220/docs/SUCCESS-SUMMARY.md` | 「聊天、**匹配、地图加载、实际对局、多人同步**及长期持续运行**未验收**」 |
| 同包 `README.md` | 「80/230 使用合法空库存/货币/entitlement 集合，**完整游戏业务与对局尚未实现或验收**」 |
| `工具-tools/launch319-reference/runtime-support/CURATION.md` | 「未新增人工大厅交互、**对局**或另一台机器验证」 |
| `技术规格-specs/1649370/ui/README.md` 系列 | 只描述 UI 路由与有界模型，「**不能由这些页面行为直接推定**」PVP 规则/匹配/对局 |

#### 结论二：目录存在但没有内容

`PVP资料-pvp/` 与 `PVE资料-pve/` 只有 README，正文是**主题规划**（`模式规则-modes/`、
`地图资料-maps/`、`房间与匹配-matchmaking/`、`对局流程-match-flow/`、`计分与结算-scoring/`），
每个版本目录下同样只有 README。**没有任何实际对局资料**。

#### 结论三：可借用的只有 UI 层线索

`技术规格-specs/1649370/ui/first-page-routes.json` 给出了房间相关的 UI 契约：

```
input_schema.room_source        = MatchService.getInstance().isInRoom
input_schema.room_object_fields = [mapID, playListID]
constants.RankedMatchStatus     = IDLE / IN_PROGRESS_IN_ROOM / BACK_FROM_GAME
BCEvent.EVT_GOTO_MATCH_SELECT   = evt_goto_match_select
continuations.setupNoRoomNavigation / setupLeaveRoomWithParty ...
```

这说明**客户端 UI 期望的输入**是「是否在房间 + mapID + playListID」，
但**没有**给出这些值从哪个 service/task 来——网络层仍需自己逆向。

#### 结论四：8 个真实任务的现状（172 个 run 汇总）

`tools/summarize_tasks.py` 扫全部历史 run 得到客户端请求过的全部任务：

| svc | task | 字节 | 出现 | 说明 |
|---|---|---|---|---|
| 71 | 4 | 3/83 | 32 | ListDedicatedServer，已有 candidate |
| 71 | 9 | 8 | 5 | FindSessions，已有 114B 条目 |
| 71 | 3 | 142/480 | 4 | 语义未知，最大 payload |
| 28 | 4 | 29 | 3 | PROGRESS.md 要求**静默** |
| 71 | 7 | 361 | 2 | 语义未知 |
| 21 | 5 | 62 | 1 | **FindLobbiesByPlaylist**（房间列表入口） |
| 11 | 13 | 3 | 1 | 内容/文件相关 |
| 102 | 5 | 12 | 1 | 未知 |

**`svc255` 与 `svc80` 从未被请求过**——所以 playerData 不是必经路径，M4.1 的重点
应从「补 svc255」转向「让 21/5 与 71/9 的应答被消费」。

#### 下一步

社区无现成方案，房间/对局需自研。优先级：

1. `svc21/task5` 已按 `bdsvc319` 默认变体（114B bdMatchMaking 条目）接上，需实测客户端是否
   在「多人竞技」页显示条目；
2. `svc71/task9` 同形状，需弄清它的触发条件；
3. 两者被消费后再谈 `svc71/task3`（142/480 字节，很可能是房间状态同步）。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.19"),
                         ("HANDOFF-CURRENT.md", "### 15.7")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.19", "### 15.7")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
