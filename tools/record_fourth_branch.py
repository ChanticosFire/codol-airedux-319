"""Record round 130: a fourth branch to the epilogue at 0xBBA611, guarded by an fp-test jp."""
from pathlib import Path

TEXT = """
### 12.145 ★★★ 存在第四条返回路径：`0xBBA611 jmp 0xBBA635`，由浮点测试的 `jp` 守护（2026-10-25 12:5x）

#### 新增工具

`tools/branches_to.py` 扫描一段代码里**所有**形式的跳转（`E9`/`EB`/`0F 8x`/`7x`/`E8`），
解析目标并与指定地址比对。`find_calls.py` 只看 `call rel32`，会漏掉 `jmp`/`jcc`。

#### 扫描结果

**指向 `0xBBA635`（函数结尾）的 4 处**：

```
0xBBA434  jne          0f85fb0100008bbd94    入口 check（状态 != 1 则返回）
0xBBA5CA  jne short    75698d8b18            状态检查（写 2 后状态不是 1 则返回）
0xBBA611  jmp short    eb220fb683            ★ 无条件返回（此前未发现）
0xBBA620  jb short     721350e8f8            容量检查（未满则返回）
```

**指向 `0xBBA55E`（写 2 入口）的 2 处**：

```
0xBBA4B2  jb           0f82a6000000          [容器+2] < 3 则去写 2
0xBBA4D3  je           0f8485000000          0xB75470 返回假则去写 2
```

#### `0xBBA611` 这条路径此前完全没被注意到

结合 §12.113 的 disassembly，`0xBBA5C3` 之后的完整结构是：

```asm
0xBBA5C3  cmp dword [ebx+0x120], 1
0xBBA5CA  jne 0xBBA635              ; 状态 != 1 -> 返回
0xBBA5CC  lea ecx, [ebx+0x118]
0xBBA5D2  call 0xB75E30
0xBBA5D7  fld dword [ebx+0x128]
0xBBA5DD  fcompp
0xBBA5DF  fnstsw ax
0xBBA5E1  test ah, 5
0xBBA5E4  jp 0xBBA613               ; ★ 奇偶标志为偶则跳过下面一段
0xBBA5E6  mov eax, [ebx+0x130]      ; ┐
          …                          ; │ 这一段以
0xBBA611  jmp 0xBBA635              ; ┘ 无条件返回结尾
0xBBA613  …
0xBBA620  jb 0xBBA635
0xBBA62B  mov dword [ebx+0x120], 3
```

**结构变成三条互斥的出口**：

| 入口条件 | 结果 |
|---|---|
| 状态 != 1 | `0xBBA5CA jne` → 返回 |
| `jp` 不成立（`ah&5` 的奇偶位为奇） | 执行 `0xBBA5E6`–`0xBBA611` → **返回** |
| `jp` 成立 | 到 `0xBBA613` → `0xBBA620` → 未满返回 / 满写 3 |

#### 这解释了"索引推进"与"写 3"如何并存

`0xBBA5E6`–`0xBBA611` 这一段（具体内容尚未反汇编）**以 `jmp 0xBBA635` 结尾**——
即它执行完自己的逻辑后直接返回，**不会到达 `0xBBA62B`**。

而 `jp` 成立时走 `0xBBA613`，那里才有容量检查与写 3。

**所以"推进索引"与"写 3"是两条不同的路径，取决于 `[ebx+0x128]` 那个浮点值的比较结果。**

#### 下一步

反汇编 `0xBBA5E6`–`0xBBA620` 的完整区间，弄清：

1. `0xBBA5E6` 那一段到底做什么（是否推进索引）；
2. `0xBBA613` 之后到 `0xBBA620` 之间的逻辑；
3. `[ebx+0x128]` 这个浮点值是什么（它决定 `jp` 的走向）。

**这可能是"状态为何最终变成 3"的关键——此前一直以为只有"索引满"一条路径能写 3，
现在发现有浮点比较参与其中。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.145"),
                         ("HANDOFF-CURRENT.md", "### 16.33")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.145", "### 16.33")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
