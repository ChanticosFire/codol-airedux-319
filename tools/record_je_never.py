"""Record round 103: the je branch never skips Add, so that candidate is eliminated."""
from pathlib import Path

TEXT = """
### 12.118 `0xBAE246` 的 `je` 从不成立：`Add` 确实每次都被调用（2026-10-24 22:5x）

#### 采样

在 `0xBAE246`（`cmp dword ptr [ebx+0x1F8], edi`）采样 `edi` 与 `[ebx+0x1F8]`：

```
[je] n=0    edi=0x00000000  [ebx+0x1F8]=0x00000000  success=0
[je] n=11   edi=0x00000000  [ebx+0x1F8]=0x00000000  success=1
[je] n=25   edi=0x00000000  [ebx+0x1F8]=0x37C2D968  success=3
[je] n=39   edi=0x00000000  [ebx+0x1F8]=0x37C2D968  success=5
…
[je] n=99   edi=0x00000000  [ebx+0x1F8]=0x37C2D968  success=13
[je] n=233  edi=0x00000000  [ebx+0x1F8]=0x37C2D968  success=13
```

**`edi` 全程为 0；`[ebx+0x1F8]` 是 obj1 指针 `0x37C2D968`。两者从不相等，
所以 `je 0xBAE292` 从不成立，`Add` 每次都被调用。**

§12.117 提出的"跳过 Add"这个候选由此排除。

#### 一个很有价值的定量观察

`0xBAE246` 在 40 秒内命中 **233 次**（约 5.8 次/秒）；同期 `success` 只涨到 **13**。

**即：`Add` 被调用 233 次，其中只有 13 次伴随一次成功接收。**

这与"pump 每帧调用、但绝大多数帧 `esi = -2`"完全一致（§12.106 的稳态观测）。

#### 但核心矛盾仍在

- `Add` 被调用 233 次 ✔
- 其中 13 次对应成功（`esi >= 0`）✔
- §12.99 已实测 `[ebp+0x94]` 在成功帧会变成 **3** ✔
- **但状态从未变成 2**（§12.117 的 20ms 采样确认）✘

若 `[ebp+0x94] = 3`，`0xBBA442 jle` 不成立，流程必然经过 `0xBBA569` 写 2。

**除非：`0xBBA43A` 读到的 `[ebp+0x94]` 与真正用于判断的那个值不是同一帧的值。**

#### 下一步：直接在 `0xBBA442` 采样

`0xBBA442` 是 `jle 0xBBA5C3`（6 字节 `0F 8E 7B 01 00 00`）。**它不在 SEH 保护区内**
（SEH 帧虽在 `0xBBA3F5` 建立，但 `0xBBA43A`–`0xBBA569` 之间没有会破坏栈的操作；
第 99 轮在 `0xBBA43A` 挂钩时客户端运行正常，可作佐证）。

在那里采样 `edi`（此时已由 `0xBBA43A` 从 `[ebp+0x94]` 载入），并与 `success` 同步记录：

- 若 `edi > 0` 而 `success` 也在涨 → `jle` 必不成立，流程必到 `0xBBA569`；
  那 §12.117 观察到的"状态从未变 2"就只能由**写入被覆盖**解释；
- 若 `edi <= 0` 始终成立（即使 `success` 在涨）→ 说明 `[ebp+0x94]` 与 `esi` 无关，
  §12.99 那次采到的 3 可能是别的东西。

**这个采样能一举判定到底是"没写"还是"写了被覆盖"。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.118"),
                         ("HANDOFF-CURRENT.md", "### 16.06")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.118", "### 16.06")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
