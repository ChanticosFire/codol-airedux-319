"""Record round 20: the firstlogin fix was counterproductive."""
from pathlib import Path

TEXT = """
### 12.36 ★★ 重大修正：firstlogin 修复反而把客户端挡在大厅之外（2026-10-23 02:5x）

#### 以前的判断是错的

§12.20 认为 `[D+0xC]=1` 让 `0x6BBF30`（firstlogin）返回 1 是"突破"，因为画面
从"选择角色"变成了"欢迎…请先取一个代号"。当时的结论是"选人界面被跳过了"。

**但从 M3 的存档证据看，这个判断方向错了。**

#### M3 的真实状态

`evidence/20261022-1604220-lobby/` 的六张截图里：

- `5-lobby-textfield.png` 显示的是**一个调试用的 TextField 测试面板**（标题 "TextField"、
  带「关闭」按钮），**背景已经是大厅**——右侧能看到 `AdministraClient`、四个游戏模式；
- `6-lobby-final.png` 是**完整大厅**：顶部「游戏大厅/开始游戏/生涯/商店/仓库/军火基地/赛事」、
  四个模式（多人竞技 PVP、勇者游戏、闯关玩法 PVE、战神排位赛）、左上「军火币商城」、
  底部「大厅群聊频道加入中…」，玩家名 **`AdministraClient`**。

而 `MILESTONES.md` 对 M3 的记述明确写着：

> 遗留：**TextField 弹窗点击**、聊天频道、业务数据填充

**即：M3 达成大厅时，代号早已存在（`AdministraClient`），客户端根本没有经过
「取一个代号」这一步。** 那个 TextField 是额外弹出的调试面板，不是代号输入框。

#### 因此 firstlogin 修复是有害的

M3 的做法是：`dw=5` 后直接调 `0x5EBE10`（cppActivate）激活前端 → 大厅显示。

而 §12.20 之后，`auto_lobby.py` 会在 `dw>=2` 时写 `[[0x3306D60]+0xC]=1`，
使 `0x6BBF30` 返回 1，FE 梯因此**继续前进**，走到了「取一个代号」这一页——
**把客户端从大厅路径上推开了**。

#### 验证（本轮实测）

去掉 firstlogin 修复、其余保持（15 处补丁 + `dw=5` 后 `ui_activate`）：

```
dw=5 reached
cs= 0 ui= 9
trampoline installed at 0x5a580000 (activates 0x5ebe10 once)
```

截图 `runs/20261023-m4-nofirstlogin/screens/n1.png`：
**画面变成空白前端背景**（蓝色粒子/网格），**不再是「取一个代号」**。

再加回 `script_state=1` + `fe_final=1`（仍不修 firstlogin），
截图 `runs/20261023-m4-combo/screens/c1.png`：同样是空白前端背景，粒子更密。

#### 现在的状态

| 配置 | 画面 |
|---|---|
| 有 firstlogin 修复 | 「欢迎…请先取一个代号」+ 输入框 |
| **无 firstlogin 修复** | **空白前端背景（已离开代号页）** |

空白前端说明：前端**已被激活**、渲染管线在跑，但 **UI 资源（`ui_mp.ff`）尚未加载**。
M3 当时是加载了的——差别在于 M3 还做了别的事。

#### 下一步（明确）

1. 读 `SOLUTION-100-111.md` 里关于大厅的记述，找 M3 当时额外做了什么；
2. 检查 `runs/20261022-1604220-min/`（M3 达成时的那次运行）的 `patch.json`，
   对比补丁集与现在的 15 处是否一致——很可能 M3 用的补丁更少或不同；
3. 若 UI 资源加载依赖某个被我们额外补丁改掉的判断，回退那处即可。

**这是自 §12.20 以来第一次让画面真正离开代号页**，方向已经纠正。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.36"),
                         ("HANDOFF-CURRENT.md", "### 15.24")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.36", "### 15.24")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
