"""Record the M3 acceptance evidence and mark the milestone in MILESTONES.md."""
from pathlib import Path

STATUS = """
### 12.18 ★★★ M3 验收达成（2026-10-22，用户录屏截图归档）

用户提供的分步截图已归档到 `evidence/20261022-1604220-lobby/`，六张覆盖完整流程：

| 文件 | 画面 |
|---|---|
| `1-character-select.png` | 选择角色（五名角色，含「选择你喜欢的角色」标题） |
| `2-character-detail.png` | 角色详情（威 / 重装兵 / 28 岁 / 82 公斤） |
| `3-welcome-tutorial.png` | 欢迎页（高手 / 新手 训练分支） |
| `4-keyboard-layout.png` | 选择键盘设置（使命召唤键位 / 其他射击游戏键位） |
| `5-lobby-textfield.png` | 大厅 + TextField 模态弹窗（未关闭） |
| `6-lobby-final.png` | **完整大厅**（关闭弹窗后） |

### M3 五项判据逐条对照

| 判据 | 证据 | 状态 |
|---|---|---|
| 1. 通过 TCLS 启动门槛 | 无 `WIN_NO_TCLS`；`DW_DNS_COMPLETE` 出现 | ✅ |
| 2. 走完 IIPS 初始化 | 无 `初始化IIPS错误`；两个 `IIPSHostApp` 进程存活 | ✅ |
| 3. Auth/LSG 请求真实到达本机 | `auth.jsonl` 有 `auth_request(188B)`→`auth_response(200)`；`lsg.jsonl` 有完整握手与 `task_request svc71/task4` | ✅ |
| 4. 可交互的原生前台/大厅 | 六张截图；`6-lobby-final.png` 显示完整大厅 UI（左侧功能栏、四大模式、军火币商城、玩家信息、聊天频道栏） | ✅ |
| 5. 留下可复验证据 | `runs/20261022-*` 全过程记录 + `evidence/20261022-1604220-lobby/` 截图 + 本文档复验命令 | ✅ |

### 完整链路（最终版）

```
TCLS 门槛（副本 + -q）
  → IIPS 初始化（高权限令牌）
  → Auth 4175（自签 TLS + 七字段响应 + 真实 Tiger 票据）
  → LSG 4174（transcript 派生密钥，不读客户端内存）
  → UDP/TCP 3074 回显（lobby_udp.py）
  → 15 处运行期补丁（6 处常规 + 9 处 pump）
  → dw=5 / ui=9 / lstate=2
  → [0x82E1340] 写 2 → FE 梯自调 cppActivate → gate=1 / G1=3
  → 大厅完整渲染
```

### 遗留（不阻塞 M3）

1. `TextField` 弹窗需点「关闭」（`tools/click_at.py --window CODO --at 1405 621`）。
2. 「大厅群聊频道加入中...」需要聊天服务端支持。
3. 大厅业务数据（公告/任务/商城列表）为空，需 `svc80`/`svc255` 应答填充。
4. `svc71/task9`、`task3` 到达不稳定，属客户端竞态。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")

    with (root / "PROJECT_STATUS.md").open("a", encoding="utf-8") as stream:
        stream.write(STATUS)
    print("PROJECT_STATUS.md updated")

    with (root / "HANDOFF-CURRENT.md").open("a", encoding="utf-8") as stream:
        stream.write(STATUS.replace("### 12.18", "### 15.6"))
    print("HANDOFF-CURRENT.md updated")

    path = root / "MILESTONES.md"
    text = path.read_text(encoding="utf-8")
    old_header = ("更新：2026-10-21（Asia/Shanghai）。**目标版本已切换为 3.19.26.17 / Build 1604220**")
    new_header = ("更新：2026-10-22（Asia/Shanghai）。**目标版本为 3.19.26.17 / Build 1604220**；"
                  "**M3 五项判据已全部达成**（证据见 `evidence/20261022-1604220-lobby/` 与 "
                  "`PROJECT_STATUS.md` §12.18）")
    if old_header in text:
        text = text.replace(old_header, new_header, 1)

    old_m3 = "| M3 原生前台与大厅 | 进行中 |"
    new_m3 = "| M3 原生前台与大厅 | **完成** |"
    if old_m3 in text:
        text = text.replace(old_m3, new_m3, 1)

    # replace the M3 row body with the acceptance statement
    marker = "| M3 原生前台与大厅 | **完成** |"
    idx = text.find(marker)
    if idx >= 0:
        end = text.find("\n", idx)
        row = ("| M3 原生前台与大厅 | **完成** | 五项判据全部达成：①TCLS 无 `WIN_NO_TCLS`；"
               "②IIPS 初始化完成、两个 `IIPSHostApp` 存活；③`auth.jsonl` 有 `auth_request(188B)`→`auth_response(200)`，"
               "`lsg.jsonl` 有完整握手与 `task_request svc71/task4`；④六张截图（`evidence/20261022-1604220-lobby/`）"
               "显示完整大厅 UI；⑤全过程 `runs/` 记录 + 复验命令见 [SOLUTION-100-111.md](SOLUTION-100-111.md) "
               "与 [PROJECT_STATUS.md](PROJECT_STATUS.md) §12.18。遗留：TextField 弹窗点击、聊天频道、业务数据填充 |")
        text = text[:idx] + row + text[end:]

    path.write_text(text, encoding="utf-8")
    print("MILESTONES.md marked M3 complete")


if __name__ == "__main__":
    main()
