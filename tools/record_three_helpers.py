"""Record round 57: the three helpers, and the remaining contradiction about writing 2."""
from pathlib import Path

TEXT = """
### 12.71 三个辅助函数的语义，以及一个尚未解开的矛盾（2026-10-23 21:1x）

#### 三者都极简

```asm
0xBC1980  mov ax, word ptr [ecx + 2]   ; 返回容器 +2 的 word
          ret
```

```asm
0xBC1970  lea eax, [ecx + 0x8c]        ; 返回数据区地址
          ret
```

```asm
0xB75470  push ebp / mov ebp,esp
0xB75473  mov dx, word ptr [ecx + 0x84]
0xB7547A  mov eax, [ebp + 8]
0xB7547D  cmp dx, word ptr [eax + 0x84]
0xB75484  jne 0xB75496                 ; +0x84 不等 -> 返回 1
0xB75486  push eax
0xB75487  call 0xB77000
0xB7548C  test al, al
0xB7548E  jne 0xB75496                 ; 0xB77000 为真 -> 返回 1
0xB75490  xor eax, eax
0xB75493  ret 4                        ; 否则返回 0
0xB75496  mov eax, 1
```

而 `0xB77000` 是 `return !0xB76FD0(arg)`（`call` 后 `test al,al` / `sete al`）。
`0xB76FD0` 正是 §12.26 查过的"类型判定"（检查 `[edx+0x80] == 0x17`）。

**所以 `0xB75470` 的返回值是**：

| 条件 | 返回 |
|---|---|
| 两个 `+0x84` 字段不相等 | **1** |
| 相等，但类型不是 `0x17`（`0xB77000` 为真） | **1** |
| 相等且类型是 `0x17` | **0** |

#### 容器构造时 `+2` 被清零

```asm
0xBC1CE9  xor eax, eax
0xBC1CEE  mov byte ptr [esi], 0
0xBC1CF1  mov word ptr [esi + 2], ax    ; ★ 条目数 = 0
0xBC1CF5  call 0xB753A0
0xBC1CFA  lea ecx, [esi + 0x8c]
```

`[ebp-0x250]` 在 `0xBBA44E call 0xBC1CC0` 后被清零，`+2` 是 **0**。

#### 由此推出的两种可能，但都与观测冲突

按第 56 轮读到的分支：

```asm
0xBBA4A9  call 0xBC1980        ; 返回 [ebp-0x250]+2 = 0
0xBBA4AE  cmp ax, 3
0xBBA4B2  jb 0xBBA55E          ; 0 < 3 -> 跳去写 2
```

`+2` 恒为 0，所以 `jb` 恒成立，**必然跳到 `0xBBA55E`，而那里就是 `0xBBA569`
写 2 之前的三条 push**。也就是说：**只要 `Add` 进入主体，就必然写 2。**

但第 52 轮实验二（容量 200、索引 0、状态 1）观察到索引一路涨到 200，
**状态却始终是 1**。这与"必然写 2"直接冲突。

#### 冲突的三种可能解释

1. **我读错了 `0xBBA55E` 的作用**——它可能不是"写 2 路径的入口"，而是别的分支
   汇合点；`0xBBA569` 也许还有别的进入条件。
2. **`Add` 调用时 `[ebp+0x94]`（count）为 0**——那样会在
   `0xBBA442 jle 0xBBA5C3` 处跳到 `0xBBA5C3`，绕过整段 `0xBBA4A1`–`0xBBA55C`，
   然后由 `0xBBA5EC` 的容量判断决定是否写 3。实验二里索引在涨，说明**确实有
   追加发生**，但追加可能来自 `0xBAE4D8` 段（复制 136 字节到 `+0x8C`），
   而 `Add` 本身因 count=0 什么都没做。
3. **索引的增长另有来源**——不在 `Add` 里。

第 2 种解释很值得检查：`0xBAE4D8`–`0xBAE51A` 那段确实把 136 字节复制进
`[ebp-0x20]` 再复制回来，而 `0xBBA496` 又复制到 `[ebx+0x8c]`。两处都改数据区，
但只有 `Add` 会改状态。

#### 下一步

用计数器验证 `Add` 的**两个分支**：在 `0xBBA4A1`（进入主体后）与 `0xBBA5C3`
（count<=0 分支）各装一个探针，在第 52 轮实验二的条件下（容量 200、索引 0、
状态 1）观察哪个命中。这能一次性区分上述三种可能。

若命中 `0xBBA5C3`，则说明 **count 恒为 0，`Add` 从未真正追加**，
索引增长另有来源——问题的位置又要往回退一层。
若命中 `0xBBA4A1` 且仍然没写 2，则说明我对 `0xBBA55E` 的解读有误。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.71"),
                         ("HANDOFF-CURRENT.md", "### 15.59")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.71", "### 15.59")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
