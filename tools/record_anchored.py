"""Record round 95: the anchored trace shows status going 1 -> 3 with no 2, while successes grow."""
from pathlib import Path

TEXT = """
### 12.110 ★★★ 锚定 `dw==5` 的高频轨迹：状态从 1 直接跳 3，中间没有 2（2026-10-24 18:5x）

#### 方法

给 `poll_counters.py` 加 `--anchor-dw`：先等客户端进程，再等 `dw`（`0x84ABA40`）
变成 5，然后以 **0.1 秒**间隔采样 `success` / `status` / `idx` / `1F4`。

本次锚点在启动后 **19.05 秒**达到，随后 12 秒的轨迹：

```
     t   success  delta  bytes  status  idx  1F4
  0.00         5           477       1    2    1
  0.10         7     +2    540       1    2    1
  0.20         7     +0    540       1    2    1
  0.50         7     +0    540       1    3    1
  0.60         9     +2    603       1    3    1
  1.00         9     +0    603       1    3    1
  1.11        11     +2    666       1    4    1
  1.51        11     +0    666       1    4    1
  1.61        13     +2    729       3    5    1     ★ 状态在此刻 1 -> 3
  1.71        13     +0    729       3    5    1
  …
  4.22        13     +0    729       3    5    1
```

#### 三个关键观察

1. **`dw=5` 之后 `success` 还在涨**（5 → 13，共 +8 次），且**每次 +2**
   （对应两字节的增量：477 → 540 → 603 → 666 → 729，每次 +63）
2. **`status` 在 t=0.00–1.51 期间一直是 1**，而 `success` 在此期间从 5 涨到 11
3. **t=1.61 时 `status` 从 1 直接变成 3**，同时 `idx` 从 4 变成 5、`success` 从 11 到 13
4. **`idx` 与 `success` 同步增长**（2→2→3→3→4→5），不是"成功时不动"

#### 这提出了一个尖锐的矛盾

按 §12.95 的结论，`count > 0` 时应当：

```
0xBBA569 写 [ebx+0x120] = 2
0xBBA5C3 cmp [ebx+0x120], 1
0xBBA5CA jne 0xBBA635      ; 2 != 1 -> 立即返回（索引不推进）
```

**若如此，`status` 应当在第一次成功时就变成 2，并且此后 `idx` 不再增长。**

实测却是：

- `status` 一直 1，直到某一刻直接跳 3；
- `idx` 与 `success` **同步**增长，说明**每一帧都走的是 `count<=0` 的路径**。

**即：`success` 在涨，但 `Add` 收到的 `count` 始终 <= 0。**

#### 于是问题变成：`esi` 到底是不是 `Add` 的 count

- §12.105（第 90 轮）在 `0xBBA418` 采到 `[ebp+0x94] == esi`，据此认定 count = `esi`；
- 但本轮显示成功在涨（`esi` 应为正）而 `Add` 仍走 `count<=0` 分支。

**两者不能同时成立。** 可能的解释：

1. **`0xBB15E0` 的成功路径返回的不是 `esi`**——`0xBB172B mov eax,esi` 之后
   可能还有别的赋值（例如 `0xBB1744` 之后的清理代码改了 `eax`）；
2. **`0xBAE244 mov esi,eax` 之后、`0xBAE276 call Add` 之前，`esi` 被别的调用改掉**——
   中间有 `0xB753C0`（复制 136 字节），而 `0xB753C0` 内部用 `esi` 做自己的变量
   （`0xB753C9 mov esi,ecx`），**它虽然是 stdcall 会恢复 `esi`……但它有 `push esi` /
   `pop esi` 吗？**
3. `0xBB15E0` 的返回值在成功时为 0（而非正），`success` 计数与该返回值无关。

**第 2 条最可疑**：`0xB753C0` 里 `mov esi, ecx` 之后有没有恢复 `esi`？
它的序言是 `push ebp / push esi / push edi`，结尾是 `pop edi / pop esi / pop ebp / ret 4`——
**有恢复**。所以 `esi` 应当保持。

**第 1 条也需要排除**：`0xBB172B mov eax,esi` 之后是 `0xBB172E adc`、
`0xBB1734 add`、`0xBB173D adc`、`0xBB1744 xor ecx,ebp`、`0xBB1746 call 0xC3C20F`、
`0xBB174B mov esp,ebp`、`0xBB174E ret`。**这些都不改 `eax`。** 所以返回值确实是 `esi`。

#### 下一步

**改用轮询而非 hook 来验证 `esi`**：在 `dw=5` 后高频轮询 `success`，
当它增长时立刻记录——但 `esi` 是寄存器，轮询读不到。

**替代方案**：hook `0xBB172B`（`mov eax,esi`，2 字节 `8b c6`）——那里没有 SEH 操作，
只有一条简单的 mov，重放安全。采样 `esi` 的实际值。若那里 `esi` 确实 >= 0，
就能确认"count 应为正"；随后再查为何 `Add` 看不到。

**这是把最后一处矛盾钉死的实验。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.110"),
                         ("HANDOFF-CURRENT.md", "### 15.98")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.110", "### 15.98")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
