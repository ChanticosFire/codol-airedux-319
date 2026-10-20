"""Append the M3 lobby milestone to PROJECT_STATUS.md and HANDOFF-CURRENT.md."""
from pathlib import Path

TEXT = """
### 12.14 ★★★ 大厅完整渲染（M3 核心达成，2026-10-22 23:4x）

把 FE 梯的 `G1` 从 0 直接写成 **2**（跳过 firstlogin 与 FE-loaded 两道自检），
梯子随后**自己**走完了最后一步：

```
before  G1=0 gate=0 session_ready=0 CS=9
now     G1=2 gate=0 session_ready=1 CS=9
now     G1=3 gate=1 session_ready=1 CS=9    ← cppActivate 已被梯子自己调用
after   G1=3 gate=1 session_ready=1 CS=9
```

`G1=3` / `gate=1` 说明 `0x5EBE10`（cppActivate）执行成功，前端正式激活。

截图 `runs/20261022-1604220-g2/screens/d1.png` 显示**完整大厅 UI**：

- 左侧菜单：`公告`、`福利`、`任务`
- 主区：`多人游戏 (PVP)`、`特种行动`、`闯关模式 (PvE)`、`自定义游戏`
- 右上：玩家名 `Administrator`、军衔 `新兵`
- 中间：`TextField` 模态弹窗（带「关闭」按钮）——与社区记录一致
- 底部：`大门解锁特追加门...`

用户亦确认「成功进入大厅」并录屏。

### 12.15 至此的完整链路

| 环节 | 手段 | 状态 |
|---|---|---|
| TCLS 门槛 | 副本 + `-q` | ✅ |
| IIPS 初始化 | 高权限令牌 | ✅ |
| Auth | 自签 TLS + 7 字段响应 | ✅ |
| LSG 握手 | transcript 派生密钥 | ✅ |
| UDP 3074 | `lobby_udp.py` 回显 | ✅ |
| lobby pump | 9 处补丁 | ✅ |
| dw=5 | `lobby_pump_ok` 等 6 处补丁 | ✅ |
| 前端激活 | `G1=2` → 梯子自调 cppActivate | ✅ `gate=1` |
| **大厅 UI** | — | ✅ **已渲染** |

### 12.16 已知遗留

1. `TextField` 模态弹窗仍在，需点击「关闭」（可脚本化或用 `tools/capture_screen.ps1` 前的点击器）。
2. 大厅数据（公告/任务/商城）为空，需要 `svc80`/`svc255` 等业务应答填充。
3. `svc71/task9`、`task3` 仍未稳定到达。

### 12.17 复验要点

`G1` 推进必须**在 dw=5 之后**、且顺序为 **0 → 2**（直接写 2）；
写 1 只会停在 `G1==1` 等 FE-loaded。工具：`python tools\\force_fe_ladder.py --to 2 --set-ready`。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name in ("PROJECT_STATUS.md", "HANDOFF-CURRENT.md"):
        path = root / name
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.1", "### 15.1")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"appended {len(body)} chars to {name}")


if __name__ == "__main__":
    main()
