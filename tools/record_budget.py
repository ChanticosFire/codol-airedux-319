"""Record round 77: limiting replies controls the index, but write-2 still does not happen."""
from pathlib import Path

TEXT = """
### 12.92 限制应答次数能控制索引，但仍未触发写 2（2026-10-24 08:5x）

#### 新增能力

```
LOBBY_UDP_REPLY_MAX=N     只回应前 N 个数据报，之后静默
```

`LobbyEndpoint.reply_budget` / `reply_sent`，`udp_reply` 事件带 `sent` 计数。

#### 结果对比

| 配置 | `obj1[0x120]` | `idx` | 成功路径计数 | `1F4` |
|---|---|---|---|---|
| 无应答 | 3 | 5 | 0 | 1 |
| `REPLY=1e8300`（不限次） | 3 | 5 | 13 | 1 |
| **`REPLY=1e8300 MAX=1`** | **1** | **2** | **7** | 1 |

**限制应答次数确实把索引压了下来**（5 → 2），说明追加次数与索引增长直接相关，
§12.91 的推断方向正确。

**但状态停在 1，`1F4` 仍为 1。** 按下列代码，这里本应写 2：

```asm
0xBBA43A  mov edi, [ebp + 0x94]      ; count
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3               ; count <= 0 -> 跳过
0xBBA448  lea ecx, [ebp - 0x250]     ; 只有 count > 0 才构造容器
0xBBA44E  call 0xBC1CC0              ; 容器 +2 = 0
...
0xBBA4A9  call 0xBC1980              ; 返回 [容器 + 2]
0xBBA4AE  cmp ax, 3
0xBBA4B2  jb 0xBBA55E                ; < 3 -> 写 2
```

容器每次调用都重新构造（`0xBC1CC0` 把 `+2` 清零），`0xBC1A50` 只追加一次，
`+2` 应当是 1，`jb` 应当成立，`0xBBA55E` → `0xBBA569` 应当写 2。
**实测没有发生。**

#### 两种解释

1. **我把 `0xBBA55E` 的角色读错了**——它可能不是"写 2 路径的入口"，
   而是别的分支的汇合点，`0xBBA569` 还有额外条件；
2. `0xBC1980` 返回的不是 1 而是 ≥ 3——例如 `0xBC1A50` 一次性把 `+2` 设成了
   本次追加的条目数，而服务端应答里声明的条目数就是 ≥ 3（我们回的是固定 3 字节，
   客户端可能把其中某个字段解释成大数）。

第 2 条很值得查：`1e 83 00` 的第三字节是 `0x00`，若客户端把它当大端或小端读取
并结合长度，完全可能得出一个大数。**换句话说，应答的"内容"现在开始起作用了，
不再只是"有数据就行"。**

#### 下一步（两条并行）

1. **反汇编 `0xBBA548`–`0xBBA5A0`**，确认 `0xBBA55E` 前后到底做了什么、
   `0xBBA569` 是否有前置条件；
2. **试不同的应答内容**：既然 `MAX=1` 已经让索引可控，那么改变第三字节或加上
   长度字段，观察 `+2`（可通过 `stat`/状态变化间接判断）是否变化。
   候选：`1e 83 01`、`1e 83 00 01 00`、`1e 83 02 00 00`。

第 1 条成本低且能直接消除歧义，优先做。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.92"),
                         ("HANDOFF-CURRENT.md", "### 15.80")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.92", "### 15.80")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
