"""Record the FE-loaded analysis and the codename dead end."""
from pathlib import Path

TEXT = """
### 12.21 FE-loaded 是三处卡点的共同根因（2026-10-23 00:4x）

#### 反汇编链

`0x6BBF60` 是设置 `onboard_character_selected` 的函数，它有两个调用者：

```asm
; caller 1 @ 0x6C1C09
0x6C1C00  call 0x730C50        ; FE-loaded
0x6C1C05  test al, al
0x6C1C07  je 0x6C1C21          ; 未加载 -> 跳过设置
0x6C1C09  call 0x6BBF60        ; 设置 onboarded

; caller 2 @ 0x73DE94
0x73DE94  call 0x6BBF60
0x73DE99  test al, al
0x73DE9B  jne 0x73DE60         ; 失败 -> 走另一分支
```

而 `0x730C50` 自身要求**全部**成立：

```asm
0x730C57  cmp [0xE59D20], 4      ; FE_state 必须 4 或 6
0x730C62  cmp [0xE59D20], 6
0x730C67  call 0x803700          ; 对象必须非空
0x730C79  cmp eax, 2             ; 0xB7A680 必须返回 2
0x730C90  cmp [0x84ABABC], 1     ; 必须 == 1
0x730CBE  cmp byte [0x82C4A86], 0; 必须非 0
```

#### 实测值

`tools/probe_fe_loaded.py` 采样（对话结束前）：

```
FE_state [0xE59D20] = 5      <- 不是 4/6，直接失败
script   [0x84ABABC] = 0     <- 不是 1
final    [0x82C4A86] = 0     <- 是 0
```

**`FE_state=5` 是第一个也是决定性的失败点**——它让 `0x730C50` 无条件返回 0，
于是 `0x6BBF60` 不被调用、`onboarded` 永不设置、FE 梯也永远卡在 `G1==0`
（FE 梯 `G1==1` 分支同样调用 `0x730C50`）。

#### 尝试与结果

| 尝试 | 结果 |
|---|---|
| 把 `[0xE59D20]` 改成 4 | **破坏状态机**，`dw` 卡在 2，永远到不了 5 |
| 只改 `[0x84ABABC]=1` 与 `[0x82C4A86]=1` | `dw` 仍能到 5，但 `FE_state` 保持 5，`0x730C50` 依旧返回 0 |
| 不加强推、等自然推进 | `FE_state` 从不变成 4/6 |

**结论**：`FE_state` 是客户端自己的前端阶段机，5 表示"登录中"。把它强改成 4
会让后续状态转换无法进行。而真正要它变成 4/6，需要在正确的时机完成某个
前端加载动作——这个动作目前没有发生，且不清楚触发条件。

#### 由此解释的三件事

1. **为什么 `onboard_character_selected` 写了没用**：它根本不在路径上，
   写入点被 `0x730C50` 挡住。
2. **为什么「取代号」页面没有任何网络请求**：前端尚未进入加载完成态，
   UI 只是静态渲染，提交按钮的处理未接上。
3. **为什么 FE 梯需要外部强推 `G1=2`**：梯子自己在 `G1==0`/`G1==1` 都依赖
   `0x730C50` 或 firstlogin，两者离线都不成立。

#### 当前判断

M4.1（档案持久化）被 `FE_state` 卡住。这条路径需要理解前端阶段机的完整
转换条件（`[0xE59D20]` 的所有写者），成本明显高于此前预期。

可选路线：

1. 追踪 `[0xE59D20]` 的写者，弄清什么条件下它从 5 变 4/6；
2. 绕过「取代号」——直接构造客户端认为已建档的状态（需要知道 UI 从哪个
   对象读取玩家名）；
3. 接受「每次启动走一次代号流程」，转而攻克房间列表的主动触发
   （`svc21/task5` / `svc71/task9` 的请求条件）。

第 3 条与 M4 验收的"房间列表可见"直接相关，且不依赖 FE 修复，优先尝试。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.21"),
                         ("HANDOFF-CURRENT.md", "### 15.9")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.21", "### 15.9")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
