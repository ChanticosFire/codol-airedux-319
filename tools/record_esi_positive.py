"""Record round 98: the success-path return is 3 or 4, so the count should be positive."""
from pathlib import Path

TEXT = """
### 12.113 ★★★ 成功路径返回 3 或 4（正数）；但 `Add` 仍未写 2（2026-10-24 20:2x）

#### 这次成功捕获了窗口

给 `probe_reg.py` 加"等字节就绪"循环——轮询目标地址直到读出预期字节才安装 hook，
既避开映像未映射的阶段，又能测出映射完成时刻：

```
[ready] image ready after 3.17s
[ready] hook 0xbb172b -> cave 0x142a0000
```

**映射在进程出现后 3.17 秒完成**，hook 随即装好；客户端还要 16 秒才到 `dw=5`，
所以钩子早已就位。

#### 采到的数据

在 `0xBB172B`（`mov eax,esi`，成功路径返回前）采样 `esi` 与 `[0xE85CB0]`：

```
[ready] n=0   esi=0x00000000  success=0
[ready] n=1   esi=0x00000143  success=0     ← 323
[ready] n=2   esi=0x00000003  success=1
[ready] n=3   esi=0x00000004  success=2
[ready] n=5   esi=0x00000004  success=4
[ready] n=6   esi=0x00000003  success=5
[ready] n=7   esi=0x00000004  success=6
[ready] n=9   esi=0x00000004  success=8
[ready] n=10  esi=0x00000003  success=9
[ready] n=11  esi=0x00000004  success=10
[ready] n=13  esi=0x00000004  success=12
```

**关键：`esi` 在成功时取值为 3 或 4（首次还有一个 0x143 = 323）。**

#### 这与"状态停在 3"直接冲突

若 `esi` 就是 `Add` 的 count（§12.105 曾如此认定），那么：

```asm
0xBBA43A  mov edi, [ebp+0x94]   ; = esi = 3 或 4
0xBBA440  test edi, edi
0xBBA442  jle 0xBBA5C3          ; 3 > 0，不跳
0xBBA448  …                     ; 走成功路径
0xBBA569  mov [ebx+0x120], 2    ; ★ 应当写 2
```

**状态应当在第一次成功时就变成 2，并永久短路。实测始终是 3。**

#### 于是 §12.105 的结论很可能是巧合

第 90 轮在 `0xBBA418` 采到：

```
esi = 0xFFFFFFFE   [0x94] = 0xFFFFFFFE
```

两者都等于 **-2**，但**这可能只是"两边都是 -2"的巧合，而不是"它们是同一个变量"**。
`-2` 是那条 WSA 错误路径的固定返回值，在两者的取值空间里都很常见。

**本轮 `esi = 3`／`4` 则给了新的判别点**：若 `[0x94]` 也是 3／4，说明它们确实是同一个
值；若 `[0x94]` 仍是 -2，则说明 `Add` 读的是**另一块内存**，只是恰好在失败帧里
两者数值相同。

#### 下一步（唯一需要做的实验）

**在 `0xBBA418` 同时采样 `esi` 与 `[ebp+0x94]`，且这次要看成功帧。**

前几轮做这个采样时都错过了窗口（采到的全是 -2）。现在既已掌握"等字节就绪 + 提前装钩"
的正确做法，应当在同一套流程里：

1. 等字节就绪（约 3 秒）；
2. 装 `0xBBA418` 的钩子（12 字节重放，含 SEH 赋值——**有风险**，但别无选择）；
3. 等客户端跑到 `dw=5`，采集成功帧。

若成功率仍因 SEH 重放而不稳，可改挂 `0xBBA43A`（`mov edi,[ebp+0x94]`，6 字节
`8B BD 94 00 00 00`）——那里没有 SEH 操作，且正好是"读 count"的那条指令，
可以直接看 `edi` 与 `esi` 是否一致。

**`0xBBA43A` 是更安全的挂点**，下轮改用它。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.113"),
                         ("HANDOFF-CURRENT.md", "### 16.01")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.113", "### 16.01")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
