"""Record round 99: Add does receive a positive count, so the write of 2 should happen."""
from pathlib import Path

TEXT = """
### 12.114 ★★★ `Add` 确实收到过正数 count（3），但状态仍是 3（2026-10-24 20:5x）

#### 这次挂点更安全，且同样捕获了窗口

改挂 `0xBBA43A`（`mov edi, dword ptr [ebp+0x94]`，6 字节 `8B BD 94 00 00 00`）——
这条指令正是"读取 count"的那一步，且**不含 SEH 操作**，比 `0xBBA418` 安全。

```
[cnt] client appeared after 0.2s
[cnt] image ready after 2.60s
[cnt] hook 0xbba43a -> cave 0x10c40000
```

#### 采样结果

同时读 `[ebp+0x94]` 与 `[0xE85CB0]`（成功计数）：

```
[cnt] n=0   [0x94]=0x00000000  success=0
[cnt] n=6   [0x94]=0xFFFFFFFE  success=3
[cnt] n=12  [0x94]=0xFFFFFFFE  success=3
[cnt] n=17  [0x94]=0x00000003  success=4     ← ★ 正数 3
[cnt] n=23  [0x94]=0xFFFFFFFE  success=5
[cnt] n=29  [0x94]=0xFFFFFFFE  success=5
[cnt] n=35  [0x94]=0xFFFFFFFE  success=7
…
[cnt] n=78  [0x94]=0x00000003  success=12    ← ★ 正数 3
```

**`[ebp+0x94]` 绝大多数时候是 `-2`，但在成功帧会变成 `3`。**

#### 这把矛盾推到了最后一个点

`Add` 的判定链：

```asm
0xBBA43A  mov edi, [ebp+0x94]   ; = 3
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3          ; 3 > 0  -> 不跳
0xBBA448  … 构造容器
0xBBA4A1  … 搬运
0xBBA4AE  cmp ax, 3
0xBBA4B2  jb 0xBBA55E           ; < 3 则直接去写 2
0xBBA4D3  je 0xBBA55E           ; 或 0xB75470 返回假也去写 2
0xBBA4D9  … 成功路径
0xBBA55E  …
0xBBA569  mov [ebx+0x120], 2    ; ★ 无论如何都会到这里
0xBBA5C3  cmp [ebx+0x120], 1    ; 现在是 2 -> 2 != 1
0xBBA5CA  jne 0xBBA635          ; -> 立即返回，状态保持 2
```

**按这条链，`count = 3` 时状态必然变成 2。实测却始终是 3。**

#### 只剩下三种可能

1. **`0xBBA569` 确实执行了，但随后被 `0xBBA62B` 覆盖成 3**——
   `0xBBA62B` 在 `0xBBA5CA` 的跳转目标 `0xBBA635` **之后**，正常不会执行到；
   除非 `0xBBA5C3` 的 `cmp` 读到的不是刚写的值（例如 `ebx` 在两条指令间被改）。
2. **`0xBBA569` 没执行**——即 `0xBBA442` 的 `jle` 实际上跳了。
   这与"`[0x94] = 3`"矛盾，除非**采样的 `[0x94]` 与 `Add` 实际读到的不是同一帧**：
   `probe_reg` 在 cave 里读的是**当前帧**的 `[ebp+0x94]`，而 `eax` 采样也来自同一帧，
   所以应当一致。
3. **`jle` 之前的某条指令改了 `edi`**——`0xBBA43A` 之后到 `0xBBA442` 之间只有
   `0xBBA440 test edi,edi`，没有别的写 `edi`。

**第 2 条最需要排除**，因为它意味着"我采到的 `[0x94]` 不是 `Add` 真正用的那个值"。

#### 下一步：直接在 `0xBBA569` 装计数器

`0xBBA569` 的指令是 `mov dword ptr [ebx+0x120], 2`，编码 `C7 83 20 01 00 00 02 00 00 00`
（10 字节，完整指令）。

**在那里装一个计数器**，就能直接回答"写 2 到底执行过没有"：

- **计数 > 0** → 写 2 确实执行过，问题是随后被覆盖 → 需要查覆盖路径；
- **计数 == 0** → 写 2 从未执行 → 说明 `Add` 根本没走成功分支，
  那 `[0x94] = 3` 的采样与 `Add` 看到的不是同一个值。

**这是把最后这层窗户纸捅破的唯一实验**，而且 `0xBBA569` 处没有 SEH、没有栈操作，
是安全的挂点。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.114"),
                         ("HANDOFF-CURRENT.md", "### 16.02")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.114", "### 16.02")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
