"""Record round 78: write-2 is unconditional, and the count<=0 branch skips past it."""
from pathlib import Path

TEXT = """
### 12.93 写 2 是无条件的；`count<=0` 分支会跳过它（2026-10-24 09:2x）

#### `0xBBA55E` 解码结果

```asm
0xBBA54B  lea eax, [ebp - 0xd8]
0xBBA551  push eax
0xBBA552  lea ecx, [ebp - 0x74]
0xBBA555  push ecx
0xBBA556  call 0xBA4B20                  ; 日志/断言
0xBBA55B  add esp, 8
0xBBA55E  push 0x63
0xBBA560  lea edx, [ebp - 0x13b]
0xBBA566  push 0
0xBBA568  push edx
0xBBA569  mov dword ptr [ebx + 0x120], 2 ; ★ 写 2
0xBBA573  mov byte ptr [ebp - 0x13c], 0
...
```

**从 `0xBBA55B` 直落 `0xBBA569`，中间没有任何条件跳转。** 也就是说：

- `count > 0` 的路径（`0xBBA448` → `0xBBA4A1` 搬运 → 判定 → `0xBBA55E`）会写 2；
- `0xBBA4D3 je 0xBBA55E`（`0xB75470` 返回假）也直接到写 2；
- **`count <= 0` 跳到 `0xBBA5C3`，而 `0x5C3 > 0x569`，所以它跳过了写 2**。

**这解释了为什么"无应答"时状态永远是 3**：`count` 恒为 0 → 走 `0xBBA5C3` →
跳过写 2 → 直接到 `0xBBA5EC` 容量检查 → 索引满 → 写 3。

#### 但仍有一处对不上

`MAX=1` 那次的观测是：

```
obj1[0x120] = 1    idx = 2    cap = 5    stat = 7
```

`stat = 7` 说明成功路径走了 7 次，`count > 0` 确实发生过；而 `idx = 2` 远小于容量 5，
容量检查应当 `jb 0xBBA635`（正常返回），**不会**写 3。

那么按 §12.93 的结论，那一刻应当留下 `0x120 = 2`。**实测却是 1。**

三种可能：

1. **写 2 之后又被写回 1**——`0x120` 的写入点除了 `0xBBA569`，还有 `0xBBA3D2`
   （写 1，在 `0xBBA370` 的 `Init` 里）。若 `Init` 在之后被调用，会覆盖成 1；
2. `0xBBA569` 执行了，但随后 `0xBBA62B`（写 3）也执行了，而我们采样时已过很久——
   但实测是 1 不是 3，所以不成立；
3. 观测到的 `1` 是"刚被 `Init` 复位、还没走完一轮"的中间态，也就是说
   `Init` 一直在周期性调用，把状态反复复位到 1。

**第 1 与第 3 条指向同一个东西：`Init`（`0xBBA370`）是否在稳态下仍被调用。**

§12.67 已确认 `0xBBA370` 有两个调用者 `0xBADD0A` 与 `0xBAE6A8`，但从未在
**稳态**下计数过它（§12.65 那次 0 次是启动期窗口问题）。

#### 下一步

给 `0xBBA370`（`Init`）装计数器，在稳态下采样。三种结果：

- **若稳态下持续被调用**：说明状态机在被反复复位，那 `0x120 = 1` 就是
  "刚复位"的正常值，而"写 2 → 2"会被下一次复位冲掉。这条路要改成
  "让上层消费掉条目、推进到别的状态"；
- **若稳态下 0 次**：则 `0x120 = 1` 只能是 `0xBBA569` 写的（因为只有它能写 2……
  但写的是 2 不是 1），矛盾说明还有第三个写 1 的地方；
- **若偶尔 1 次**：说明触发条件已满足过一次，值得追那次的时间和上下文。

这是目前最需要确认的一件事。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.93"),
                         ("HANDOFF-CURRENT.md", "### 15.81")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.93", "### 15.81")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
