"""Record round 122: Add runs about 27 times a second, so the two-per-second reading was wrong."""
from pathlib import Path

TEXT = """
### 12.137 ★★★ `Add` 实际约 27 次/秒，推翻"2 次/秒"的假设（2026-10-25 08:5x）

#### 方法

先用 `poll_counters --anchor-dw` 等到 `dw=5`（19.48 秒到达），**再**在 `0xBBA3F3`
（`Add` 入口）装钩子，采样 10 秒。

#### 结果

```
[rate2] final n=269  dw=5  success=13
```

**10 秒内 `Add` 被调用 269 次——约 26.9 次/秒。**

#### 这推翻了此前的推断

§12.131 与 §12.135 曾根据"`idx` 每 0.52 秒 +1"推断"`Add` 约 2 次/秒"，
并据此认为 `success` 的增长与 `Add` 无关（"巧合"解释）。

**实际频率是 27 次/秒，与 `idx` 的 2 次/秒相差 13 倍。**

**所以"`Add` 调用频率低"这个前提不成立。**

#### 由此得到的新图景

在状态为 1 的窗口内（`dw=5` 之后约 2.5 秒），`Add` 大约跑 67 次，
但 `idx` 只推进了 5 次。

**即：约 62 次调用没有推进索引，5 次推进了。**

按 `Add` 的判定链：

| 分支 | 结果 | 是否推进索引 |
|---|---|---|
| `count <= 0` | 跳到 `0xBBA5C3`，状态 1 不短路 → `0xBBA5E6` +1 | **是** |
| `count > 0` | 写 2 → `jne` → 返回 | **否** |

**若 62 次是 `count>0`（不推进）、5 次是 `count<=0`（推进），那 62 次都应当写 2，
状态早该是 2。**

**但状态始终是 1。**

#### 矛盾已无退路

当前所有可靠观测放在一起：

1. `Add` 约 27 次/秒（本轮）；
2. `count`（`[ebp+0x94]`）在 `dw=5` 后反复为 **3/4**（§12.133，77 次稳定采样）；
3. `obj1[0x120]` 从 1 直接跳 3，从未是 2（§12.131，5ms 轮询）；
4. 写 2 在 `dw=2` 时执行过（§12.108，唯一可信命中）；
5. 五个中间 `call` 不破坏 `ebx`（§12.124/125）；
6. `Init` 只运行 1 次（§12.131）。

**按 2+5+6，`count>0` 的调用必然写 2 并返回；按 3，状态从未是 2。**

**这只能意味着：`0xBBA43A` 处采到的正值，与 `Add` 在 `0xBBA442` 用于判断的 `edi`
不是同一个值。**

#### 最后一个可验证的假设

`0xBBA43A` 是 `mov edi, dword ptr [ebp+0x94]`。**若 `[ebp+0x94]` 在两条指令之间被改动**
（例如被某个异步/中断/其它线程写入），采样到的正值与判断时读到的值就可能不同。

**但更可能的是：`[ebp+0x94]` 本身是一个会被反复改写的栈槽，而
`0xBBA43A` 与 `0xBBA442` 之间没有指令改动它——所以这个假设站不住。**

#### 换个角度：直接看 `count` 的分布

既然 `Add` 27 次/秒而 `idx` 只 2 次/秒推进，**统计 `[0x94]` 的取值分布**就能判断：

在 `0xBBA43A` 采样 500 次，统计其中正数、零、负数的比例。

- 若**绝大多数为正** → 那 62 次不推进的调用都是 `count>0`，它们都该写 2 → 矛盾加深，
  说明"写 2 后没有返回"；
- 若**绝大多数为负** → 那 62 次不推进的调用是 `count<=0` 却**没有**推进索引 →
  说明 `0xBBA5C3` 的 `jne` 在状态为 1 时**也被跳了**，即状态读到的不是 1。

**这个统计能把矛盾劈成两半，指向具体的一侧。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.137"),
                         ("HANDOFF-CURRENT.md", "### 16.25")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.137", "### 16.25")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
