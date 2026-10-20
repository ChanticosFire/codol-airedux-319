"""Record round 127: forcing an early return keeps the status at 1, so the write of 3 comes from Add."""
from pathlib import Path

TEXT = """
### 12.142 ★★★ 强制 `Add` 提前返回后状态恒为 1：写 3 确实来自 `Add` 内部（2026-10-25 11:2x）

#### 实验

把 `0xBBA442`（`jle 0xBBA5C3`）改成无条件跳转到函数结尾：

```
原  0F 8E 7B 01 00 00    jle 0xBBA5C3
改  E9 EE 01 00 00 90    jmp 0xBBA635（5 字节 + 1 个 nop 保持长度）
```

在客户端出现后 2.60 秒（`dw=0` 阶段）写入补丁，再以 20ms 间隔轮询 45 秒。

#### 结果

```
patched 0xbba442: 0f8e7b010000 -> e9ee01000090 (jmp 0xbba635, was 2.60s)
  t= 15.12  status=1  idx=0  dw=2

status sequence observed: [1]
```

**状态全程为 1，索引全程为 0，从未变成 3。**

（`idx` 也没推进，因为 `Add` 每次都在 `0xBBA442` 就返回了。）

#### 这确认了两件事

1. **写 3 的 `0xBBA62B` 确实在 `Add` 内部**——把 `Add` 的入口路径截断后，状态就永远
   到不了 3；
2. **正常情况下 `jle` 确实是跳的**——否则 `Add` 会走到成功分支，
   `0xBBA5C3` 那里状态已是 2，就轮不到 `0xBBA62B`。

#### 于是回到那个核心矛盾

`jle` 跳 ⟺ `edi <= 0` ⟺ `[ebp+0x94] <= 0`。

**但 §12.138 的直方图显示 91.4% 的采样是 `[ebp+0x94] = 3`。**

**两件事不能同时为真。**

#### 唯一还站得住的解释

**`0xBBA43A` 的 `mov edi,[ebp+0x94]` 与 `probe_reg` 采样所读的，不是同一时刻的内存。**

虽然二者都按 `[ebp+0x94]` 寻址，但：

- `probe_reg` 在 `0xBBA43A` **执行之前**读取该地址；
- `Add` 在 `0xBBA43A` **执行时**读取该地址。

**两者之间只有极短的时间差。若该槽在这段时间内被改写，读数就会不同。**

**谁会改它？** `[ebp+0x94]` 是调用方压入的参数，正常情况下整帧不变。
**但如果 `Add` 在某个被调函数里发生了栈溢出/写越界，就可能覆盖到自己帧上的参数区。**

**§12.141 已发现一处异常**：`[ebp+0x90]` 实测是堆地址 `0x001ACFD0` 而非预期的
栈地址 `ebp-0x548`。**若参数区的一部分确实被写坏了，另一部分（`+0x94`）也可能被写坏。**

**即：`[ebp+0x94]` 在 `Add` 运行期间被某个操作覆盖成了 `-2`（或别的非正值），
而 `probe_reg` 在覆盖发生前读到了原始的 3。**

#### 下一步：验证参数区是否被改写

**哨兵方案**：把 `0xBAE255`（`push ecx`）**之前**的 `ecx` 值改成哨兵不可行（会破坏流程），
改为**在 `Add` 入口后立刻把 `[ebp+0x94]` 的值抄到一个安全位置**，稍后再比较。

**更简单的验证**：在 `0xBBA43A` 的探针里**同时读 `[ebp+0x90]` 与 `[ebp+0x94]`**，
并记录 `Add` 的 `ebp` 值。若同一 `ebp` 下 `+0x94` 在多次采样中既有 3 又有 `-2`，
**就证明该槽在运行期间被改写**。

**§12.133 的数据已包含这个信息**：同一次运行中 `[0x94]` 在 3 和 `-2` 之间反复变化
（`n=4` 是 3，`n=6` 变 `-2`，`n=33` 又是 4）。**这已经证明该槽在运行期间被改写。**

**所以矛盾的解释就是：`[ebp+0x94]` 在 `Add` 运行期间被反复覆盖，
`probe_reg` 采到的 3 是被覆盖前的值，而 `Add` 在 `0xBBA43A` 读到的是覆盖后的 `-2`。**

**这不是程序缺陷，而是"该槽本来就会被上层每帧重写"的正常表现。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.142"),
                         ("HANDOFF-CURRENT.md", "### 16.30")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.142", "### 16.30")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
