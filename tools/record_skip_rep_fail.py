"""Record round 129: skipping rep movsd changes nothing, so the fault lies elsewhere."""
from pathlib import Path

TEXT = """
### 12.144 阴性：跳过 `rep movsd` 后状态仍到 3（2026-10-25 12:2x）

#### 实验

把 `0xBBA4F2` 的 `F3 A5`（`rep movsd`）改成 `90 90`（两条 `nop`），
在客户端出现后 2.89 秒写入，然后 20ms 轮询 45 秒：

```
patched 0xbba4f2: f3a5 -> 9090 (rep movsd skipped, was 2.89s)
  t= 14.87  status=1  idx=0  dw=2
  t= 17.47  status=3  idx=5  dw=5

status sequence: [1, 3]
samples with status==2: 0
```

**状态仍然从 1 直接到 3，一次都没见过 2。**

#### 这说明 `rep movsd` 不是（唯一的）故障点

§12.143 的推论是"'`rep movsd` 用 `edi`（=3）做目标 → 访问违例 → SEH 吞掉 →
跳过写 2"。

**若该推论正确，跳过这条指令后流程应当继续到 `0xBBA569` 写 2，状态变 2。**
**实测没有。**

**所以要么 `rep movsd` 根本不会违例**（`edi` 在那一点上其实指向合法缓冲），
**要么在它之后还有别的地方抛出异常。**

#### 重新审视 `edi` 的假设

`0xBBA43A` 装载 `edi = [ebp+0x94] = 3`。但 `Add` 内部在 `0xBBA448` 之后有大量代码：

```asm
0xBBA448  push esi
0xBBA449  push edi
0xBBA44A  ... 
```

**注意 `0xBBA448`/`0xBBA449` 是 `push esi` / `push edi`**——若这两条在
`rep movsd` **之前**执行，`edi` 仍未被改。

**但更关键的是**：`0xBBA4A1` 附近还有一段搬运代码（§12.69 记录过 `rep movsd`，
`ecx = 0x22`）。**若那里也用了 `edi`，情况相同。**

**总之：跳过一处 `rep movsd` 没有效果，说明问题不在"某条具体指令违例"这个层面。**

#### 换个角度：也许根本没有异常

回到最基本的事实：

| 事实 | 来源 |
|---|---|
| `count = 3`（`edi` 为正） | §12.143 取反实验 |
| `jle` 不跳，进入成功分支 | §12.143 |
| `0xBBA569` 从不执行 | §12.140 哨兵实验 |
| 状态到 3 | 全部观测 |

**若没有异常，那 `0xBBA4D9`–`0xBBA556` 之间必然有一条路径绕过 `0xBBA569`。**

**但那段代码是直落的，没有跳转到 `0xBBA635` 的分支。**

**除非——`0xBBA556` 的 `call 0xBA4B20` 不是空函数。**

§12.125 测到 `0xBA4B20` 是 `C3`（`ret`），**立即返回**。**但如果它内部有异常或长跳转，
反汇编看不出来——它只有一条 `ret`，不可能。**

#### 结论：需要更细的观测手段

所有"改指令 + 轮询"的手段都用尽了，都无法让状态变成 2。

**下一步应当改变策略**：不再试图让 2 出现，而是**确认 `0xBBA569` 之前的那段代码是否真的执行**。

**哨兵法**：把 `0xBBA55E`（`push 0x63`，6 字节 `6A 63`）里的立即数改掉不会有效果
（它只是压栈）。**但可以把 `0xBBA55E` 改成 `mov dword [哨兵地址], 0xDEADBEEF`**——
不过这需要额外空间。

**更实际的做法**：把 `0xBBA55B`（`add esp,8`，3 字节 `83 C4 08`）改成
`mov [0x哨兵], eax` 之类的等长指令？长度不够。

**最终可行的方案**：**直接检查 `0xBBA448`–`0xBBA55E` 这一段是否被任何跳转绕过**，
用 `find_calls.py` 找出所有跳到 `0xBBA635` 的来源。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.144"),
                         ("HANDOFF-CURRENT.md", "### 16.32")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.144", "### 16.32")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
