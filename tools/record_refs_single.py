"""Record round 92: the success counter has exactly one write site, so the hook probably interferes."""
from pathlib import Path

TEXT = """
### 12.107 `0xE85CB0` 只有一个写入点；因此上一轮的"恒为 -2"很可能是 hook 干扰（2026-10-24 17:0x）

#### 引用枚举

用 `tools/find_refs.py`（从活动进程读 imm32 引用）扫全镜像：

```
[0xE85CB0] -> 0xBB1736     total 1 ref
[0xE85CB4] -> 0xBB173F     total 1 ref
```

两处都落在成功路径的 `add`/`adc` 指令操作数里（`0xBB1734 add dword [0xE85CB0],1`、
`0xBB173D adc dword [0xE85CB4],0`）。

**结论：成功计数确实只有这一个写入点，没有第二条来源。**

#### 于是产生一个硬矛盾

| 观测 | 值 |
|---|---|
| 第 87 轮，`dw=5` 后采样 40 秒 | `stat` 从 **23** 涨到 **95**（成功 72 次） |
| 本轮，探针装好后采样 45 秒 | `esi` 恒为 **-2**（0 次成功） |

而 `0xBB1734` 只在 `0xBB1646 jns 0xBB170C` 之后执行，`jns` 检查的正是 `esi`。
**若 45 秒内一次成功都没有，`stat` 不可能上涨；反之若 `stat` 在涨，`esi` 必然出现过 >= 0。**

两者不可能同时为真。

#### 最可能的解释：探针本身改变了行为

本轮挂在 `0xBBA418`，重放的是 **12 字节**：

```
0xBBA418  64 A3 00 00 00 00    mov dword ptr fs:[0], eax    ; ★ SEH 链节点赋值
0xBBA41E  8B B5 90 00 00 00    mov esi, dword ptr [ebp+0x90]
```

**`mov fs:[0], eax` 是 SEH 异常链的安装操作。** 把它搬进 cave、再跳回来，
虽然语义上等价，但存在两个风险：

1. cave 所在的内存（`VirtualAllocEx` 分配）不在原模块的 `.text` 范围内，
   某些异常处理/栈回溯逻辑可能会受影响；
2. 该指令与紧随其后的 `mov esi,[ebp+0x90]` 之间若跨了页边界被拆开，
   在极端情况下也可能出问题。

更关键的是：**如果这个 hook 让 `Add` 抛出的异常无法正常处理，`Add` 可能
提前退出**，从而根本走不到后面的收包流程——这就能解释"45 秒零成功"。

#### 与之前几轮 hook 结果的对照

历次在 `Add` 附近挂钩的结果都不太稳定：

| 轮次 | 挂载点 | 现象 |
|---|---|---|
| 83 | `0xBBA440` | 采到 2 次后客户端退出 |
| 84 | `0xBBA440` | 采到 2 次后客户端退出 |
| 89 | `0xBBA440` | 采到 2 次后客户端退出 |
| 90 | `0xBBA418` | 稳定跑到 239 次 |
| 91 | `0xBBA418` | 稳定跑到 537 次，但 `esi` 恒 -2 |

**挂在 `0xBBA440`（`test edi,edi`，8 字节重放）每次都导致客户端退出；
挂在 `0xBBA418`（12 字节，含 SEH 赋值）虽然稳定，但可能改变了成功路径的行为。**

也就是说：**两种挂法都不可靠**，之前基于它们的定量结论需要重新审视。

#### 更可靠的做法

1. **改挂 `0xBB170C`（成功路径入口）**——那里没有 SEH 操作，且只在成功时执行。
   若它稳定计数为 0，才能确证"稳态下没有成功"；
2. 或**不挂钩，改为定期轮询 `[0xE85CB0]`**：这个全局量本身就是成功次数的
   精确指标，轮询它不会干扰任何代码。
3. 轮询方案最稳妥：`dw=5` 之后每隔 1 秒读一次 `[0xE85CB0]`，看它是否增长。

**第 3 条零风险且能直接判定上一轮结论是否成立**，下轮先做这个。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.107"),
                         ("HANDOFF-CURRENT.md", "### 15.95")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.107", "### 15.95")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
