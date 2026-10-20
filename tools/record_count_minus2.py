"""Record round 83: Add receives -2 as its count, because the argument block is shifted."""
from pathlib import Path

TEXT = """
### 12.98 ★★★ `Add` 收到的 count 是 `-2`（WSA 错误码），因为参数块整体错位（2026-10-24 12:1x）

#### 实测

在 `0xBBA440`（`mov edi, [ebp + 0x94]` 的下一条 `test edi, edi`）采样 `edi`：

```
[addcount] n=0  edi=0x00000000  (0)
[addcount] n=1  edi=0xFFFFFFFE  (-2)
```

**`edi = -2`，正是 `0xBB166F`（`WSAEWOULDBLOCK` 分支）返回的值。**

#### 重新推演栈布局

`0xBAE24E` 起的调用序列：

```asm
0xBAE24E  push esi                    ; ① 最高地址
0xBAE255  push ecx                    ; ② ecx = ebp-0x548
0xBAE256  sub esp, 0x88               ; 136 字节结构
0xBAE26A  push edx                    ; ③ 最低地址（0xB753C0 的源指针）
0xBAE26B  call 0xB753C0               ; cdecl，返回后 esp 仍指向 ③
0xBAE276  call 0xBBA3F0               ; Add 的 call 又压入返回地址
```

`Add` 里 `push ebp / mov ebp, esp` 之后，`[ebp+8]` 是返回地址之上的第一个 dword：

| 偏移 | 内容 |
|---|---|
| `[ebp+0x04]` | 返回地址 |
| `[ebp+0x08]` | ③ 的 `edx` 副本（4 字节） |
| `[ebp+0x0C]` .. `[ebp+0x93]` | 136 字节结构（0x88 字节） |
| **`[ebp+0x94]`** | **结构之后的第一个 dword = ② 的内容，即 `[ebp-0x548]`** |

**所以 `[ebp+0x94]` 不是"结构 +0x84"，而是结构**之后**的一块内存——正是虚函数
的输出参数 `[ebp-0x548]`。**

而 `[ebp+0x90]` 是结构内偏移 `0x84`（`0x90 − 0x0C = 0x84`），即**端口 3074**。

#### 于是 `Add` 的两个参数都是错的

| 参数 | `Add` 的用途 | 实际内容 |
|---|---|---|
| `[ebp+0x90]` | 源数组指针 | 结构 `+0x84` = **端口 3074** |
| `[ebp+0x94]` | count | **`[ebp-0x548]` = -2**（错误码） |

`count = -2` → `0xBBA440 test edi,edi` → `0xBBA442 jle 0xBBA5C3` → **跳过写 2**。

**这与全部观测完全一致**：

- 无论我们回不回包、回多少次，`count` 始终由那个输出参数决定；
- 失败帧里它是 -2，成功帧里它是别的值（§12.97 采到的 `eax = 0x11050C02` 是
  `0xCA84D4` 的返回值，而输出参数是另一路）；
- `count <= 0` 恒成立 → `Add` 永远走 `0xBBA5C3` → 推进索引 → 满则写 3。

#### 为什么 §12.97 里 `eax` 会变成 `0x11050C02`

那是 `call dword ptr [0xCA84D4]` 的**返回值**，被 `mov word [ebx], ax` 写进
容器的 `+0x84`（`ebx` 来自 `[ebp+0x10]`，指向 `&[ebp-0x120]`，与 `Add` 读的
`[ebp+0x90]` 不是同一块内存）。**两条数据流是分开的**，所以一个变化不影响另一个。

#### 这解释了为什么此前所有调参都无效

- 改容量 → 只影响"索引何时满"，不影响 `count`；
- 改应答频率 → 只影响成功帧比例；
- 改应答内容 → 影响的是写进 `+0x84` 的值，而 `Add` 根本不读那里。

**`count` 的来源是 `[ebp-0x548]`，也就是虚函数第 2 个参数指向的缓冲区。**
只有当虚函数往里写了正数时，`Add` 才会走成功分支。

#### 下一步

1. 在 `0xC74041`（`mov edx, [ebp - 0x120]`）与 `0xC74047`（`mov ecx, [ebp - 0x11C]`）
   处采样，看虚函数到底把什么写进了这两个输出参数；
2. 特别关注 `[ebp-0x548]`（即 `Add` 眼里的 count）在**成功帧**里的取值——
   若它恒为负或 0，那说明虚函数的输出语义与 `Add` 的期望不一致，
   这可能是客户端自身的一个缺陷，也可能是我们缺少某个上层初始化。

**关键**：现在知道该看哪个变量了——不是容器的 `+0x84`，而是虚函数的
第 2 个输出参数。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.98"),
                         ("HANDOFF-CURRENT.md", "### 15.86")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.98", "### 15.86")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
