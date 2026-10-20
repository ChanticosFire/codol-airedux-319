"""Record round 93: a pure read confirms all 13 successes happen within the first 3 seconds."""
from pathlib import Path

TEXT = """
### 12.108 ★★★ 无 hook 纯轮询确认：13 次成功全部发生在启动后 0–3 秒（2026-10-24 17:4x）

#### 零干扰观测

新增 `tools/poll_counters.py`——只读内存，不装任何 hook：

```
COUNTERS:
  0xE85CB0  成功计数（0xBB1734 add）
  0xE85CB4  高位
  0xE85CA0  字节累计（0xBB1725 add）
  0xE85CA4  高位
```

结果（每 3 秒采样一次，共 70 秒）：

```
    t     success   delta      bytes
  0.0           9                603
  3.0          13      +4        729
  6.0          13      +0        729
  9.0          13      +0        729
  …
 69.0          13      +0        729
```

**三个事实：**

1. **成功总共 13 次，全部在 0–3 秒内完成**（`t=0` 已有 9 次，`t=3` 到 13 次）；
2. **此后 66 秒完全静止**，`delta` 恒为 `+0`；
3. **字节累计 729 字节也静止**，与 13 次成功一一对应。

#### 这解决了 §12.107 的矛盾

第 87 轮看到 `stat` 从 23 涨到 95，**那是当时的观测有误**——很可能是因为
`0xBBA418` 的 hook 重放了 SEH 安装指令，改变了行为，或者采样点本身受到干扰。

**本轮用纯读的方式确认：稳态下根本没有成功。** 第 91 轮"稳态恒为 -2"的结论成立，
第 92 轮对 hook 干扰的怀疑也有道理——但干扰的方向是**让数字变多**（87 轮的 95），
而不是让它们变少。

**13 与 729 是每次运行都相同的常量**，说明这是客户端启动流程的固定行为
（很可能是 TLS/LSG 通道上的几次收发，与 3074 的探测包无关）。

#### 窗口结构最终确认

```
t=0        客户端启动
t=0–3s     ★ 13 次成功（0xBB15E0 返回 >= 0），累计 729 字节
t≈2.5s     索引涨满 -> 写 3 -> 状态锁定（若此前没写 2）
t≈23-24s   客户端发出第一个 UDP 探测包（此时已无任何成功）
```

**成功的窗口是 0–3 秒，探测包在 23 秒——相差 20 秒，永远不可能重叠。**

#### 下一个关键问题

那 13 次成功里，`esi`（返回值）应当 `>= 0`。**如果其中任何一次发生时状态仍是 1，
`Add` 就应该写 2 并永久短路。** 但状态最终是 3，说明：

- 要么 13 次全都发生在状态已变 3 之后（即索引在 3 秒内就满了）；
- 要么写 2 之后又被覆盖；
- 要么这 13 次成功走的不是 `Add` 那条路（例如来自另一个对象/另一条通道）。

**下一轮应当高频轮询**（每 0.1–0.2 秒一次）**同时记录 `success` 与 `obj1[0x120]`
和 `idx`**，把这 3 秒内的演化看清。若能在某次成功时抓到 `status == 1` 且
随后变成 2，就直接证明窗口可行；若抓到的 `status` 一直是 3，则说明索引在
成功到来前就已填满，需要让 `Init` 后的索引涨得更慢。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.108"),
                         ("HANDOFF-CURRENT.md", "### 15.96")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.108", "### 15.96")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
