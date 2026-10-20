"""Record round 102: 20ms polling shows the status never passes through 2."""
from pathlib import Path

TEXT = """
### 12.117 ★★★ 20ms 轮询：状态从未经过 2，且索引在成功之前就已填满（2026-10-24 22:2x）

#### 方法：不挂钩，纯轮询

`poll_counters.py` 增加 `--only-changes`（只在数值变化时打印）。以 **0.02 秒**间隔、
从 `dw==5` 起采样 6 秒。**任何持续 20 毫秒以上的状态都必然被捕获。**

```
     t   success  delta  bytes  status  idx  1F4
  0.00         5           477       1    2    1
  0.04         6     +1    508       1    2    1
  0.06         7     +1    540       1    2    1
  0.49         7     +0    540       1    3    1
  0.53         8     +1    571       1    3    1
  0.57         9     +1    603       1    3    1
  1.00         9     +0    603       1    4    1
  1.04        10     +1    634       1    4    1
  1.06        11     +1    666       1    4    1
  1.51        11     +0    666       1    5    1   ← 索引已满，状态仍是 1
  1.53        12     +1    697       3    5    1   ← 状态直接跳 3
  1.57        13     +1    729       3    5    1
```

#### 三个确定的结论

1. **状态从未经过 2**——20ms 采样下不可能漏掉；
2. **`idx` 在 t=1.51 时已达容量 5，而状态仍是 1**——说明此前所有帧都在走
   `count <= 0` 的路径（只有那条会推进索引）；
3. **状态在 t=1.53 从 1 直接变 3**，恰好在 `idx` 满了之后、下一次成功发生时。

#### 这与"成功时 count 为正"再次冲突

若 t=1.53 那次成功让 `Add` 拿到正数 count：

```asm
0xBBA442  jle 0xBBA5C3     ; count > 0 -> 不跳
…
0xBBA569  mov [ebx+0x120], 2
0xBBA5C3  cmp [ebx+0x120], 1   ; 现在是 2
0xBBA5CA  jne 0xBBA635          ; -> 返回，状态保持 2
```

**状态应当变成 2 并保持。实测变成了 3，且索引没有继续增长。**

反过来，若 t=1.53 那次 `Add` 拿到的 `count <= 0`：

```asm
0xBBA442  jle 0xBBA5C3
0xBBA5C3  cmp [ebx+0x120], 1   ; 仍是 1
0xBBA5CA  jne 不成立 -> 继续
0xBBA5E6  mov eax, [ebx+0x130]  ; 索引 = 5
… +1 -> 6
0xBBA61A  cmp [ebx+0x130], 容量 ; 6 > 5
0xBBA62B  mov [ebx+0x120], 3    ; ★ 状态变 3
```

**这完全吻合观测**：状态变 3、索引保持 5（`+1` 之后被容量检查拦下，写 3 并返回）。

**所以 t=1.53 那次成功时，`Add` 拿到的 `count` 仍然是 `<= 0`。**

#### 于是矛盾重新指向"`success` 增长但 `esi` 非正"

`success` 只在 `0xBB1734` 递增，而那是 `0xBB1646 jns 0xBB170C` 之后——
`jns` 意味着 `esi >= 0`。**若 `success` 涨了，`esi` 当时必然 >= 0。**

第 98 轮也确实在 `0xBB172B` 采到 `esi` 为 3、4（正数）。

**唯一的协调方式**：`esi >= 0` 的那些调用与 `Add` 看到 `count <= 0` 的调用**不是同一次**。

即：**虚函数成功的那些帧，其返回值没有传到 `Add`。**

这与第 101 轮的观察一致——`0xBAE244 mov esi,eax` 之后到 `0xBAE276 call 0xBBA3F0`
之间只有：
- `0xBAE246 cmp dword [ebx+0x1F8], edi`
- `0xBAE24C je 0xBAE292`（**关键！**若相等则整个 Add 调用被跳过）
- `0xBAE24E push esi`
- `0xBAE255 push &[ebp-0x548]`
- `0xBAE256 sub esp, 0x88`
- `0xBAE26B call 0xB753C0`（stdcall，复制 136 字节）
- `0xBAE276 call 0xBBA3F0`

**`0xBAE24C je 0xBAE292` 是一个此前未被重视的岔路**：当 `[ebx+0x1F8] == edi` 时
跳过 Add。`edi` 在此处的值来自函数更早的部分——若它在某些帧里恰好等于
`obj1` 指针，Add 就被跳过。

**下轮应当确认 `edi` 在 `0xBAE246` 处的取值**，以及那个 `je` 的命中率。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.117"),
                         ("HANDOFF-CURRENT.md", "### 16.05")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.117", "### 16.05")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
