"""Record round 59: +0x84 is the port, not a count; and +0x130 has no fourth writer."""
from pathlib import Path

TEXT = """
### 12.73 数组条目的 `+0x84` 是**端口**不是数量；`+0x130` 没有第四个写入点（2026-10-23 22:1x）

#### 数组记录的实际内容

`[lobby+0x4D60]` 那条 136 字节记录（`0x35F7D7A0`，容量 1，游标 0）完整转储：

```
+0x00  7f 00 00 01 00 00 ...     127.0.0.1
+0x10  …全部为 0…
+0x70  …全部为 0…
+0x80  02 00 00 00
+0x84  02 0c 20 00
```

关键字段：

| 偏移 | 值 | 含义 |
|---|---|---|
| `+0x00` | `7f 00 00 01` | IP = 127.0.0.1 |
| `+0x80` | `02 00 00 00` | 类型/族（dword 2） |
| `+0x84` | **`02 0c`** | **word = 0x0C02 = 3074** —— **端口号** |

**`+0x84` 是端口，不是条目数。**

这修正了 §12.71/§12.72 的推断。`0xB75470` 里 `cmp dx, [eax+0x84]` 比较的是
**两个条目的端口是否相同**，而 `0xB77000` → `0xB76FD0` 检查的是"类型是否为 0x17"。
两者合起来是"**是否指向同一服务端点**"的判定。

#### `count` 不是来自这条记录

`Add` 的 count 取自 `[ebp+0x94]`，即传给它的那个 136 字节结构（由
`0xBAE24E`–`0xBAE26B` 从 `[ebp-0x768]` 复制到栈）的 `+0x84`。

而数组条目确实有 `+0x84 = 3074`。所以问题变成：**`[ebp-0x768]` 是否就是
数组条目的副本？**

从 §12.49 已知另一条路径把数组条目复制到 `[ebp-0x658]`（`0xBAE5FF`–`0xBAE612`）。
而 `0xBAE25C` 复制的是 `[ebp-0x768]`。**两个不同的局部缓冲**。
若 `[ebp-0x768]` 从未被数组条目填充，它的 `+0x84` 自然是 0，count 也就是 0。

**下一轮应当直接读 `[ebp-0x768]` 的内容**——但它是栈地址，需要先抓 pump 的
`ebp`。更简单的替代：在 `0xBAE26B` 之后读栈上的副本（即 `esp` 指向处）。

#### `+0x130` 没有第四个写入点

补扫 `0xBB0000`–`0xBBC000` 的三种"读-改-写"形式：

```
01 /r  add [reg+0x130], r32     0 命中
83 /0  add [reg+0x130], imm8    0 命中
FF /0  inc dword [reg+0x130]    0 命中
total 0
```

加上 §12.65 已扫到的 `89 /r`、`C7 /r`、`FF /0`，`+0x130` 的写入点就是三个：

- `0xBB76BB`（构造，写 `eax` = 0）
- `0xBBA3A6`（初始化，写 0）
- `0xBBA5F6`（追加路径，`mov [ebx+0x130], edx`）

**而 `0xBBA5F6` 位于 `0xBBA5C3` 之后**，`count <= 0` 的分支不会执行它。

#### 于是存在一个尚未解开的矛盾

第 52 轮实验二观测到 `obj1+0x130` 从 0 涨到 200（约 2 条/秒）。
但：

- `count` 恒为 0（§12.72 实测 body 分支 0 次）；
- `+0x130` 的三个写入点里，只有 `0xBBA5F6` 会递增式地改它，而它不可达；
- 机器码里没有任何 `add`/`inc` 形式改它。

**三种可能**：

1. 第 52 轮脚本读错了字段（当时读 `o1+0x130`，可能 `o1` 指针已变）；
2. `0xBBA5C3` 那条路径里存在**跨函数的**递增（例如调用某个方法改 `+0x130`）；
3. `0x130` 在别处被当作结构体的一部分整体覆盖（例如 `rep movsd` 复制到
   `[ebx+0x8c]` 时越界写到了 `+0x130`，但那方向不对：`+0x8c` 加 136 = `0x114`，
   够不到 `0x130`）。

第 3 条值得注意：`[ebx+0x8c] + 136 = [ebx+0x114]`，而 `+0x130` 在更后面，
所以 `rep movsd` 不会覆盖它。

#### 下一步

1. **抓 pump 栈帧，直接读 `[ebp-0x768]`**，确认它的 `+0x84` 是否为 0，
   从而确认 `count = 0` 的直接来源；
2. **重新测一次 `obj1+0x130` 的变化**，这次同时记录 `obj1` 指针与 `lobby` 指针，
   排除"指针变了导致读错对象"的可能。

第 2 条成本极低，且能立刻判断矛盾是观测错误还是真实异常。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.73"),
                         ("HANDOFF-CURRENT.md", "### 15.61")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.73", "### 15.61")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
