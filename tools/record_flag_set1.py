"""Record round 153: [ebp-0x989] does get set to 1, at 0xBAE28D when eax differs from 1."""
from pathlib import Path

TEXT = """
### 12.168 ★★★ `[ebp-0x989]` 并非恒为 0：`0xBAE28D` 会在 `eax != 1` 时置 1（2026-10-26 01:5x）

#### 全镜像搜索

`find_offset.py 0xFFFFF677`（即 `[ebp-0x989]` 的 disp32）在 `0x400000`–`0xDD0000` 内：

```
0xBAD864   C6 85 77 F6 FF FF 00    mov byte ptr [ebp-0x989], 0     ← 初始化
0xBAE28D   C6 85 77 F6 FF FF 01    mov byte ptr [ebp-0x989], 1     ← ★ 写入 1
0xBAE2EC   80 BD 77 F6 FF FF 00    cmp byte ptr [ebp-0x989], 0     ← 守卫检查
0xC84F92   …（另一函数帧的 ebp，与本 pump 无关）
```

**所以 §12.167 的"死结"推断不成立——这个标志确实有置 1 的路径。**

#### `0xBAE28D` 的上下文

```
0xBAE280  … 83 F8 01        cmp eax, 1
0xBAE285  … 74 07           je +7
0xBAE28D  C6 85 77 F6 FF FF 01   mov byte ptr [ebp-0x989], 1
```

**即：`cmp eax, 1` / `je`（跳过下一条）——只有当 `eax != 1` 时才把标志置 1。**

#### pump 入口附近的完整初始化

```asm
0xBAD83D  cmp byte ptr [edi], 0                ; [lobby+8]（§12.158 实测为 1）
0xBAD840  je 0xBAE7C6                           ; 为 0 -> 复位返回
0xBAD846  cmp dword ptr [ebx+0x1F4], 1          ; ★ 要求 1F4 == 1
0xBAD84D  jne 0xBAE7C6                          ; 不等于 1 -> 复位返回
0xBAD853  mov eax, dword ptr [ebx+0x18]         ; lobby+0x18
0xBAD856  cmp dword ptr [ebx+0x4D70], eax       ; 与另一个字段比较
0xBAD85C  lea ecx, [ebx+0x208]
0xBAD862  mov byte ptr [ebp-0x989], 0           ; 标志清零
0xBAD869  mov byte ptr [ebp-0x986], 0
0xBAD870  mov dword ptr [ebp-0x9B0], eax
0xBAD876  sete byte ptr [ebp-0x988]             ; 相等则为 1
0xBAD87D  call 0xBAEF50
0xBAD882  lea ecx, [ebx+0x208]
0xBAD888  test al, al
0xBAD88A  je 0xBAD896
0xBAD88C  call 0xBAF610
0xBAD891  jmp 0xBAD989
0xBAD896  call 0xC74720
0xBAD89B  cmp eax, 6
```

#### 这解释了为什么三道守卫会挡住

**`[ebp-0x989]` 在 `0xBAD862` 被清零，只有 `0xBAE28D` 会把它置 1。
而 `0xBAE28D` 位于 `0xBAE000` 之后、`0xBAE2EC` 之前——即在同一遍 pump 里。**

**所以每次 pump 调用都会：先清零 → 中间某处可能置 1 → 边界检查。**

**若 `eax != 1` 在那个 `cmp` 处成立，标志就为 1，守卫通过。**

**而实测 `1F4` 恒为 1，说明守卫**未**通过——即 `eax == 1`。**

#### 下一步

**反汇编 `0xBAE270`–`0xBAE2A0`**，找出：

1. `eax` 从哪来（在 `cmp eax,1` 之前）；
2. 什么条件下 `eax != 1`。

**这能确定"要让守卫通过，需要在哪个变量上满足什么条件"。**

**同时值得注意 `0xBAD846 cmp [ebx+0x1F4],1` / `jne 0xBAE7C6`**——
**pump 要求 `1F4 == 1` 才会继续——这与"要把它变成 2"看似矛盾。**

**即：`1F4` 是 1 时 pump 才执行主体逻辑；而主体逻辑又试图把 `1F4` 变成 2。
一旦变成 2，下一帧 pump 就会因 `jne` 直接跳到复位。**

**这可能是一条"应当先变成 2、再由别的路径复位为 1"的循环——
说明 `1F4` 是个"帧内脉冲"而非"持久状态"。**

**这个认识很重要：`1F4` 不需要"保持"为 2，只需要在某一帧短暂变成 2 即可。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.168"),
                         ("HANDOFF-CURRENT.md", "### 16.56")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.168", "### 16.56")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
