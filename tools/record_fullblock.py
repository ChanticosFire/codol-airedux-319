"""Record round 131: the full block, and a previously unnoticed call to 0xBBA1F0."""
from pathlib import Path

TEXT = """
### 12.146 ★★★ 完整代码：索引 +1 后分两路，未满时调用 `0xBBA1F0`（2026-10-25 13:2x）

#### `0xBBA5E6`–`0xBBA62B` 全文

```asm
0xBBA5E6  mov eax, dword [ebx+0x130]      ; eax = 旧索引
0xBBA5EC  movzx ecx, byte [ebx+0x124]     ; ecx = 容量
0xBBA5F3  lea edx, [eax+1]                ; edx = 索引+1
0xBBA5F6  mov dword [ebx+0x130], edx      ; ★ 索引 = 索引 + 1
0xBBA5FC  cmp eax, ecx                    ; 旧索引 vs 容量
0xBBA5FE  jae 0xBBA613                    ; 旧索引 >= 容量 -> 已满分支
0xBBA600  push ecx
0xBBA601  push edx
0xBBA602  call 0xBA4B20                   ; 日志（空函数）
0xBBA607  add esp, 8
0xBBA60A  mov ecx, ebx
0xBBA60C  call 0xBBA1F0                   ; ★ 未满时调用
0xBBA611  jmp 0xBBA635                    ; 返回

0xBBA613  movzx eax, byte [ebx+0x124]     ; 已满分支：读容量
0xBBA61A  cmp dword [ebx+0x130], eax      ; 新索引 vs 容量
0xBBA620  jb 0xBBA635                     ; 未满（不可能，刚判定已满）-> 返回
0xBBA622  push eax
0xBBA623  call 0xBA4B20                   ; 日志
0xBBA628  add esp, 4
0xBBA62B  mov dword [ebx+0x120], 3        ; ★ 写 status = 3
0xBBA635  …                               ; 函数收尾
```

#### 关键发现：`0xBBA1F0` 是一个此前未分析过的函数

这是本轮最重要的发现。**在"索引 +1 且未达容量"的正常路径上，`Add` 会调用 `0xBBA1F0`。**

第 107 轮的反汇编曾显示它的开头：

```asm
0xBBA1F0  push ebp
0xBBA1F1  mov ebp, esp
0xBBA1F3  sub esp, 0x514              ; ★ 1300 字节局部
0xBBA1F9  mov eax, [0xE3F240]         ; 栈 cookie
0xBBA1FE  xor eax, ebp
0xBBA200  mov [ebp-4], eax
0xBBA203  push ebx
0xBBA204  push esi
0xBBA205  mov esi, ecx                ; esi = this（即 obj1）
0xBBA207  xor ebx, ebx
0xBBA209  cmp dword [esi+0x120], 1    ; ★ 也检查状态
```

**它有自己的 1300 字节栈帧，且同样检查 `[this+0x120] == 1`。**

#### 为什么这很重要

`[ebx+0x120]` 的全部 8 个写入点（§12.70）里，有一个是 **`0xBBA2B6 -> 4`**，
而 `0xBBA2B6` **落在 `0xBBA1F0` 的函数体内**（`0xBBA1F0` 起始，`0xBBA2B6` 在 +0xC6 处）。

**所以这条路径有可能把状态写成 4。**

但实测状态是 3，说明 `0xBBA2B6` 没有执行到——**`0xBBA1F0` 内部可能还有别的分支
提前返回**。

#### 这可能是整条链的最后一环

`Add` 在"追加一条记录"时会调用 `0xBBA1F0`（可能名为"消费/结算"），
而后者会检查状态、可能改写它。

**若 `0xBBA1F0` 内部把状态从 2 改回 1（或改到别的值），那"写 2 立即失效"就有了解释**——
但 §12.120 的哨兵实验证明写 2 从不执行，所以这条路径不影响那个结论。

**更可能的是：`0xBBA1F0` 是"真正推进状态机"的地方**，
而 `Add` 只是个前置过滤器。

#### 下一步

反汇编 `0xBBA1F0` 的完整函数体（`sub esp,0x514` 说明它不小），重点关注：

1. `0xBBA2B6`（写 4）的条件；
2. `0xBBA0A4`（写 `esi`）在哪里——若它也在附近，可能与 `0xBBA1F0` 相关；
3. 它是否调用 `0xBBA3F0`（`Add`）——若是，则存在递归调用链。

**这是目前最值得追的一条线。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.146"),
                         ("HANDOFF-CURRENT.md", "### 16.34")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.146", "### 16.34")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
