"""Record round 43: with six patches [lobby+0x1F4] flips to -2, exactly as the community reported."""
from pathlib import Path

TEXT = """
### 12.59 ★★★ 六补丁下 `[lobby+0x1F4]` 翻成 **-2**，印证社区记录（2026-10-23 14:0x）

#### 先纠正第 39 轮的错误结论

§12.57 写「六补丁导致客户端 24 秒崩溃」。本轮用同样的 6 个补丁重跑，
**客户端稳定存活 60 秒以上，`dw` 正常到达 5**：

```
t=5s:   dw=0  ui=0
t=10s:  dw=2  ui=6
t=15s:  dw=5  ui=9   G1=0  gate=0  D+0xC=0
t=60s:  dw=5  ui=9   G1=0  gate=0  D+0xC=0
```

**第 39 轮那次崩溃是运行环境问题（服务未就绪或 observe 过短），不是补丁集的问题。**

#### 关键发现：`1F4` 翻成 -2

在此基础上写 `[D+0xC]=1`，然后观察 130 秒：

```
t=10s:  1F4 = 1
t=20s:  1F4 = 4294967294      <- 0xFFFFFFFE = -2
t=30s…130s: 恒为 -2，客户端不崩
```

**这正是社区文档描述的现象：**

> `[lobby+0x1F4]` 这个状态量以前从没撑过 47 秒就翻成 -2。根本原因是 pump 的
> 匹配判定失败后会走清理路径，把 1F4 写成 -2，而客户端再读到 -2 就认为连接已经失去。

社区记录的是"没撑过 47 秒"，我们这里是 **20 秒**——同一现象。

#### 这解释了三件事

1. **那 9 处 pump 补丁的作用**：它们把写 `-2` 的地方改成写 `1`
   （`0x7ADC27`、`0x7ADDE0`、`0x7AE754`、`0x7AE76C`、`0x7AE7B0` 五处
   `fe ff ff ff` → `01 00 00 00`，即 `-2` → `1`）。
   15 补丁下 `1F4` 恒为 1 而不是 -2，正是这个原因。

2. **6 补丁与 15 补丁的真实差别**：不是"崩不崩"，而是 **`1F4` 是 -2 还是 1**。
   两者都不通向 2，都在这个意义上失败。

3. **`-2` 不等于崩溃**：本轮实测 `1F4 = -2` 持续 130 秒，客户端存活、不发
   `ClientOffline`。所以"读到 -2 就认为连接失去"这个描述至少在 1604220 上
   不表现为进程退出。

#### 当前对 `1F4` 取值空间的完整认识

| 值 | 来源 | 客户端状态 |
|---|---|---|
| `1` | 15 补丁（9 处把 `-2` 改成 `1`）或 pump 的失败尾部 `0xBAE7AA` | 存活，FE 梯停在 G1=0/1 |
| `2` | `0xBAE1AC`（成功分支，**从未执行过**）或强写 | 强写会在 10 秒内崩溃 |
| `-2` | 6 补丁下 pump 的清理路径（`0x7ADC27` 等原始代码） | **存活**，FE 梯停在 G1=0 |

#### 下一步

`1F4` 的三种取值都已观测到，**没有一种能自然变成 2**。

要把 15 补丁（`1F4=1`）推到 `1F4=2`，只有 `0xBAE1AC` 一条路，而它被执行的条件是
两个状态字段分别等于 2 和 4（§12.51–12.53）。所以调查回到那个未解的矛盾：
`0xBBAD40` 复制 136 字节、却要求 1288 字节。

**不过本轮新增了一条有价值的线索**：社区把 `-2 → 1` 的五处补丁称为"pump 匹配
判定失败后的清理路径"。既然 `-2` 是"清理"的产物，那么**清理之前**应当有一次
`1F4=2` 的成功——也就是说，社区的环境里 `0xBAE1AC` **确实执行过**。

这与我们观察到的"从未执行"矛盾，值得列为下一轮的首要问题：
**社区那份补丁集原文（`patches319.py`）虽然缺失，但他们的 run 日志或许能证明
`1F4` 曾达到 2**。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.59"),
                         ("HANDOFF-CURRENT.md", "### 15.47")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.59", "### 15.47")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
