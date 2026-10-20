"""Record round 119: the 0xBBA442 anchor crashes every time, invalidating round 104's conclusion."""
from pathlib import Path

TEXT = """
### 12.134 ★★★ `0xBBA442` 的挂点每次都崩溃；第 104 轮的结论不可靠（2026-10-25 07:2x）

#### 三次运行完全一致

在 `0xBBA442`（`jle 0xBBA5C3`）装探针，三次独立运行：

```
[e1] n=1  edi=0xfffffffe  dw=2     → unreadable
[e2] n=1  edi=0xfffffffe  dw=2     → unreadable
[e3] n=1  edi=0xfffffffe  dw=2     → unreadable
```

**每次都只记录到第 1 次命中就崩溃。**

#### 这推翻了第 104 轮

§12.119 曾在同一位置采到 `edi = 0xFFFFFFFE`（`success = 1`），据此得出
"`jle` 成立、写 2 不执行"的结论。

**但那次也是崩溃前的第 1 次记录**——与本次三次完全相同的模式。
**该结论不能作为证据。**

#### 为什么这个挂点特别危险

`0xBBA43A`（紧邻，`mov edi,[ebp+0x94]`）能稳定运行 77 次（§12.133），
而 `0xBBA442`（`jle`）每次都崩。差别在于：

- `0xBBA43A` 重放的是一条**纯数据传送**指令，不改变控制流；
- `0xBBA442` 重放的是一条**条件分支**指令。虽然 `probe_reg` 的 cave 有
  `pushfd`/`popfd` 保护标志位，但分支指令的语义依赖于**精确的地址与标志**，
  而 cave 位于模块外、且 `pushfd`/`popfd` 之间还插入了 `pushad`/`popad` 与实际采样代码。
  **任何在标志或栈上的细微偏差都会让分支走向错误的目标，进而破坏程序状态。**

**结论：`0xBBA442` 不能作为挂点，任何在该处的采样结果都不可信。**

#### 方法论教训（值得记录）

本项目里已经多次出现"崩溃的运行被当作有效证据"：

| 轮次 | 挂点 | 现象 | 后续 |
|---|---|---|---|
| 83/84/89 | `0xBBA440` | 2 次命中后崩溃 | 当时未警觉 |
| 101 | `0xBBA569` | 客户端不启动 | 已记录 |
| 104 | `0xBBA442` | 2 次命中后崩溃 | **结论被误用** |
| 117 | `0xBBA5AB` | 1 次命中后崩溃 | **结论被误用，第 118 轮推翻** |
| 119 | `0xBBA442` | 3 次均 1 次后崩溃 | 本轮确认不可用 |

**规则：任何"命中次数 < 预期"的观测，必须先排除"客户端已崩溃"这一解释，
否则不能用于推断行为。**

#### 当前状态重新梳理

已经**可靠**确认的事实（用不崩溃的挂点或纯轮询获得）：

1. `Add` 的 count 就是 `[ebp+0x94]`，也等于虚函数返回的 `esi`（§12.105、§12.120，三次验证）；
2. `dw=5` 之后该值反复出现 **3 或 4**（§12.133，77 次稳定采样）；
3. `obj1[0x120]` 从 1 直接跳到 3，从未是 2（§12.131，5ms 轮询）；
4. `Init` 只运行 1 次，在 `dw=2`，把状态从 0 置 1（§12.131、§12.132）；
5. 写 2 在 `dw=2` 时执行过（§12.108，`0xBBA5AB` 那唯一一次可信的命中）；
6. 五个中间 `call` 都不破坏 `ebx`（§12.124、§12.125）。

**矛盾依旧：count 为正却从未见状态 2。**

#### 下一步：放弃挂钩，改用"结果侧"观测

既然控制流类的挂点都不可靠，改从**结果**反推：

**在 `dw=5` 之后，以 5ms 间隔同时轮询 `obj1[0x120]` 与 `obj1[0x130]`，
并在每次 `idx` 变化时记录 `success` 的瞬时值。**

- 若某个 `idx` 变化点对应 `success` **未变**，那是 `count<=0` 帧；
- 若对应 `success` **已变**，那可能是 `count>0` 帧；
- 通过统计两类帧的比例，可以推断 `count>0` 的帧是否存在、以及它们是否推进了索引。

**若所有 `idx` 变化都发生在 `success` 未变的时刻，说明 `count>0` 的帧从不推进索引
（与"写 2 后返回"一致），那状态就该是 2——回到矛盾；**
**若 `idx` 也随 `count>0` 帧推进，则说明写 2 从未发生——指向"`[ebp+0x94]` 与 `edi`
并非同一条路径"。**

这不需要任何 hook，是最安全的下一步。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.134"),
                         ("HANDOFF-CURRENT.md", "### 16.22")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.134", "### 16.22")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
