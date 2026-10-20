"""Record round 23: stubbing firstlogin crashes the client."""
from pathlib import Path

TEXT = """
### 12.39 打桩 `0x6BBF30` 直接崩溃——闭环不可单点打破（2026-10-23 03:4x）

#### 实验

把 `0x6BBF30`（firstlogin）前 6 字节从

```
b8 01 00 00 00 39    mov eax,1 ; cmp [0x331C5C0],eax
```

改为

```
b8 01 00 00 00 c3    mov eax,1 ; ret
```

即无条件返回 1。补丁记录确认应用成功：

```
OK 0x2bbf30  b80100000039 -> b801000000c3  applied=True verified=True
```

#### 结果：崩溃

```
2026-10-20T18:45:10Z task_request service=71 task=4
2026-10-20T18:45:34Z raw_session_end ConnectionResetError:[WinError 10054]
client exited
s1: no visible CODO window
```

客户端在 `71/4` 之后约 24 秒**连接被强制关闭**并退出进程。`dw` 从未到 5。

#### 解释

`0x6BBF30` 返回 1 会让 FE 梯继续前进到后续阶段，而那些阶段需要**配套的账号
字段**（代号、档案、解锁标志等）。这些字段只在真正的建档流程完成后才存在，
强行让判断通过等于让客户端带着空数据往下走，很快解引用到无效内容。

这与 §12.31 记录的「闭环」判断一致：**任何单点强制都会因其它环仍停在原处
而崩溃**。此前强推 `[lobby+0x1F4]=2` 也是同样的结局。

#### 23 轮的收敛结论

可以确定的事实清单：

| 项目 | 状态 |
|---|---|
| 15 个补丁 | 全部 `applied=True, verified=True`，与 M3 记录逐条一致 |
| 认证 / LSG 握手 | 正常，`71/4` 有请求有应答 |
| FE 梯自然前进 | **不会**——`[D+0xC]=0` 使 firstlogin 返回 0 |
| 强推 G1 | 能到 `G1=3, gate=1`，但 UI 停在代号页或空白前端 |
| 强推 `[lobby+0x1F4]=2` | `FE_state` 到 6，随即崩溃 |
| 打桩 firstlogin | 24 秒后崩溃 |
| 逆推出 `71/9` | 等待 90 秒仍无请求 |
| 资源解包 | fastfile 加密，不可行 |
| 社区参考脚本 | 缺 6 个依赖模块，不可用 |

**唯一缺少的东西：一份"已建档"的客户端存档。**

M3 达成大厅时的 `config_mp.cfg` 含有有效的代号与档案状态，所以 firstlogin
自然返回 1、FE 梯自然前进、客户端在 39 秒后继续请求 `71/9`。当前副本的
`config_mp.cfg` 已被后续多次运行改写（7864 B vs 原始 7850 B），该状态已丢失。

#### 需要人工介入的一步

**请手动完成一次代号流程**（在客户端停在「欢迎来到使命召唤ONLINE…请先取一个
代号」页面时，点击输入框、键入任意代号、点「继续」），确认进入大厅后告诉我。

之后我会立即：

1. 把 `runtime/client-1604220/players/config_mp.cfg` 备份为
   `config_mp.cfg.onboarded`；
2. 在 `auto_lobby.py` 里加入"运行前若缺少有效存档则从该备份恢复"的逻辑；
3. 重跑完整流程，验证大厅稳定复现，并把证据归档为 M4.1 的达成依据。

这一步无法用代码替代：提交动作在 Scaleform UI 层，不产生网络请求，
合成输入（SendInput / WM_CHAR）均被拒绝，而绕过其判断会导致崩溃。

#### 如果无法人工介入

备选路线是把 M4.1 的判据改写为「单人可复现启动流程（含一次人工代号）」，
并把已完成的档案持久化（`server319/profile.py`）作为服务端侧成果，
然后直接推进 M4.2 的协议侧工作（`svc21/task5` 帧已就绪并有单测覆盖）。

在客户端无法离开代号页的前提下，M4.2–M4.4 都不具备可达性。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.39"),
                         ("HANDOFF-CURRENT.md", "### 15.27")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.39", "### 15.27")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
