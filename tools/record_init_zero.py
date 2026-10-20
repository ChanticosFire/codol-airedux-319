"""Record round 79: Init is not called in steady state, so nothing resets the status."""
from pathlib import Path

TEXT = """
### 12.94 `Init` 稳态下 0 次调用；状态 1 是瞬态而非复位（2026-10-24 09:5x）

#### 计数结果

在 `LOBBY_UDP_REPLY=1e8300` + `MAX=1` 的环境下，给 `0xBBA370`（`Init`）装计数器
（重放 13 字节：`55 | 8B EC | 53 | 8B D9 | 83 BB 20 01 00 00 00`，逐条数过）：

```
[init] total after 15s = 0
state: 1F4=1  o1[120]=3  idx=5  stat=13
```

**`Init` 在稳态下从不被调用。**

#### 这排除了两种解释

- **"周期性复位"不成立**：若 `Init` 反复执行，计数器会明显非零；
- **"写 2 后被写回 1"也不成立**：`0x120` 写 1 的唯一位置是 `0xBBA3D2`，
  它在 `Init` 内，而 `Init` 0 次。

#### 同一配置两次结果不同，说明 1 是瞬态

| 轮次 | 配置 | `obj1[0x120]` | `idx` | `stat` |
|---|---|---|---|---|
| 77 | `MAX=1` | **1** | **2** | 7 |
| 79 | `MAX=1`（同） | **3** | **5** | 13 |

同一配置、同样的应答，两次分别停在 `1/2` 与 `3/5`。差别只能来自**采样时刻**：
第 77 轮在流程早期取样，看到的是"刚写过 2 但还没被覆盖"的中间态；
第 79 轮等计数器跑完 15 秒，已经是终态 3。

**所以 `MAX=1` 并不会改变最终结果，只影响到达终态的速度。**

#### 由此得到的机制

结合 §12.93 与本节，`Add` 的单次调用流程应当是：

```
[count > 0]
  0xBBA448  构造容器
  0xBBA4A1  搬运
  0xBBA4AE  判定（< 3 则跳到 0xBBA55E）
  0xBBA569  写 [ebx+0x120] = 2        ← 状态短暂变为 2
  0xBBA573 …
  0xBBA5EC  读容量 [ebx+0x124]
  0xBBA5F6  [ebx+0x130] = eax + 1     ← 索引仍被推进
  0xBBA61A  cmp [ebx+0x130], 容量
  0xBBA620  jb  0xBBA635              ← 未满则返回，2 得以保留
  0xBBA62B  mov [ebx+0x120], 3        ← 满了则覆盖成 3
```

**关键：写 2 与"索引推进 + 容量检查"在同一次调用里顺序发生，后者可以把前者覆盖掉。**

所以"写 2"能否保留，取决于那一刻**索引是否已到容量**。而索引从 0 涨到 5
只要约 2.5 秒，此后 `Add` 每次进入都会把状态写成 3。

#### 真正要解决的问题变了

不再是"怎样让它写 2"，而是：

> **在索引涨满之前，如何让 `Add` 不再每帧进入、或者让上层把索引复位？**

两种可能：

1. **状态 2 本应让 `Add` 短路**（`0xBBA426 cmp [ebx+0x120],1` / `jne 0xBBA635`），
   但同一个调用内就被覆盖成 3，所以短路从未生效——**这是一个设计上的竞态**；
2. 正常流程里应当有另一段代码**消费**这些条目并把 `+0x130` 复位。

第 1 条意味着：只要能在写 2 之后**阻止同一次调用继续执行 `0xBBA5F6`**，
状态就会停在 2，而 `Add` 从此短路。这恰好可以由一个**极小的补丁**实现：
把 `0xBBA620` 的 `jb` 改成无条件跳转（或在写 2 之后直接 `jmp 0xBBA635`）。

#### 下一步

考虑用一个实验性补丁验证上述判断：在 `0xBBA569`（写 2）之后紧接着插入
`jmp 0xBBA635`，让本次调用立即返回、跳过索引推进与容量检查。
若状态随即稳定在 2、且 `1F4` 变成 2，就证明这条路径是唯一障碍。

**注意**：这是运行期补丁（`patch_runtime.py` 的既有能力），属于允许范围；
但必须先确认 `0xBBA573` 之后到 `0xBBA635` 之间没有必须执行的清理逻辑，
否则会造成泄漏或崩溃。下轮先反汇编 `0xBBA573`–`0xBBA5C3` 再决定。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.94"),
                         ("HANDOFF-CURRENT.md", "### 15.82")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.94", "### 15.82")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
