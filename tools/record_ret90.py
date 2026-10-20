"""Record round 126: ret 0x90 pins Add's parameter block at exactly 144 bytes."""
from pathlib import Path

TEXT = """
### 12.141 ★★★ `ret 0x90`：`Add` 的参数块恰好 144 字节，与调用方压栈完全吻合（2026-10-25 10:5x）

#### `0xBBA635` 不是异常处理器，而是正常函数结尾

```asm
0xBBA635  lea ecx, [ebp + 8]
0xBBA638  mov dword ptr [ebp - 4], 0xFFFFFFFF    ; SEH 状态置 -1（表示无异常）
0xBBA63F  call 0xB76EE0                          ; 毒化 [ebp+8]（第一个参数）
0xBBA644  mov ecx, dword ptr [ebp - 0xc]
0xBBA647  mov dword ptr fs:[0], ecx              ; ★ 恢复前一帧 SEH 链
0xBBA64E  pop ecx
0xBBA64F  pop edi
0xBBA650  pop esi
0xBBA651  pop ebx
0xBBA652  mov ecx, dword ptr [ebp - 0x10]
0xBBA655  xor ecx, ebp
0xBBA657  call 0xC3C20F                          ; __security_check_cookie
0xBBA65C  mov esp, ebp
0xBBA65E  pop ebp
0xBBA65F  C2 90 00           ret 0x90            ; ★ 弹出 144 字节参数
```

**这是一段标准的 MSVC 函数收尾序列**：注销 SEH 帧、弹保存的寄存器、
校验栈 cookie、恢复栈、`ret N` 清参数。

**所以 §12.140 提出的"SEH 异常接管"不成立**——`0xBBA635` 只是正常返回路径，
`0xBBA5CA jne 0xBBA635` 的含义就是"条件满足则直接返回"。

#### `ret 0x90` 给出了决定性的信息

`ret 0x90` 表示调用方压了 **0x90 = 144 字节**参数，由被调方清理。

对照调用方 `0xBAE24E`–`0xBAE276`：

```asm
0xBAE24E  push esi                    ; 4 字节
0xBAE255  push ecx                    ; 4 字节（ecx = ebp-0x548）
0xBAE256  sub esp, 0x88               ; 136 字节
0xBAE26A  push edx                    ; 4 字节（0xB753C0 的源，ret 4 会弹掉）
0xBAE26B  call 0xB753C0               ; stdcall，ret 4
0xBAE276  call 0xBBA3F0               ; Add，ret 0x90
```

**136 + 4 + 4 = 144** —— **与 `ret 0x90` 完全吻合。**

**这就确定了 `Add` 的参数布局**：

| 偏移 | 内容 | 长度 |
|---|---|---|
| `[ebp+0x08]` .. `[ebp+0x8F]` | 136 字节结构 | 136 |
| `[ebp+0x90]` | `push ecx` 的值（`ebp-0x548`） | 4 |
| `[ebp+0x94]` | `push esi` 的值（虚函数返回值） | 4 |

**`Add` 里 `mov esi,[ebp+0x90]`（源数组）与 `mov edi,[ebp+0x94]`（count）
恰好对应这两个参数——布局完全正确，没有错位。**

#### 这与实测值冲突

- `[ebp+0x94]` 实测为 **3 或 4**（§12.138，91.4% 的情况）——这是 `esi`，即虚函数返回值；
- 但 §12.113 在 `0xBB172B` 采到虚函数返回的 `esi` 也是 3 或 4 —— **两者一致 ✔**；
- `[ebp+0x90]` 实测为 `0x001ACFD0`（**堆地址**），而按布局应当是 `ebp-0x548`（**栈地址**）—— **两者不符 ✘**。

#### 只剩一处未对上

`[ebp+0x90]` 应当是 `ecx` 的值，而 `0xBAE24F` 处 `lea ecx, [ebp-0x548]` 显然是栈地址。

**实测却是堆地址 `0x001ACFD0`。**

**两种可能**：

1. **`0xBAE24F` 的 `lea ecx,[ebp-0x548]` 之后、`0xBAE255` 的 `push ecx` 之前，
   `ecx` 被改成了别的值**——但这两条指令相邻，中间没有别的指令；
2. **`[ebp+0x90]` 不是 `push ecx` 的结果**——即结构实际是 140 字节而非 136，
   或者 `[ebp+8]` 不是结构起点。

**第 2 条可以用 `ret 0x90` 排除**：144 − 4 − 4 = 136，结构必然是 136 字节。
**所以结构起点必然是 `[ebp+8]`，`[ebp+0x90]` 必然是 `push ecx` 的结果。**

**结论：`[ebp+0x90]` 应当是栈地址，但实测是堆地址——这一处仍未解释。**

#### 下一步

用**哨兵法**验证 `[ebp+0x90]` 的真实来源：把 `0xBBA41E`（`mov esi,[ebp+0x90]`）
之后的某条指令改成写入一个哨兵值到某处，观察 `Add` 看到的是什么。

**或者更直接**：在 `0xBAE255`（`push ecx`）前后各打一个哨兵，比较 `ecx` 的值。

**但这一处已不影响主线**：`count = [ebp+0x94] = esi = 虚函数返回值`，
而 `ret 0x90` 确认了布局正确。**哨兵实验证明 `0xBBA569` 从未执行**，
**这才是核心事实**——`count=3` 却从不写 2，只能说明 `0xBBA442` 之后到 `0xBBA569`
之间仍有未明的路径。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.141"),
                         ("HANDOFF-CURRENT.md", "### 16.29")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.141", "### 16.29")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
