"""Record round 34: writer candidates for the two status fields."""
from pathlib import Path

TEXT = """
### 12.52 两个状态字段的写入点候选（2026-10-23 10:1x）

#### 已确认的确定性写入

`0xBBAD40` 内部就有对 `+0x1A0` 的写入：

```asm
0xBBAD95  mov dword ptr [ebx + 0x1a0], 1     ; 标记"已处理"
```

而 `0xBBA810`（容器构造）会把它清 0：

```asm
0xBBA871  mov dword ptr [esi + 0x1a0], 0
```

所以 `obj2` 的 `+0x1A0` 至少经历过 `0 → 1`。**实测当前是 5**，说明还有别的推进者。

#### 全局扫描结果

对 `0x400000`–`0x10000000` 全区间扫描 `mov dword [reg+0x1A0], r32`
（`89 /r` 带 disp32）与 `mov dword [reg+0x120], r32`：

```
mov [+1A0], r  modrm 0x81 (ecx): 0x848BD4, 0x85C592, 0xAD16B3
mov [+1A0], r  modrm 0x82 (edx): 0x85C993
mov [+1A0], r  modrm 0x83 (ebx): 0x8461D7? -> 0x461D7C
mov [+1A0], r  modrm 0x86 (esi): 0x4B4263, 0x4B5F19, 0x4B60DF, 0x4DA033, 0x4EBE0B
mov [+120], r  modrm 0x81 (ecx): 0x48F357, 0x8BAAD3
mov [+120], r  modrm 0x83 (ebx): 0x461BF8, 0x6CEE82, 0xA67874, 0xA67C04, 0xBB76BB
mov [+120], r  modrm 0x86 (esi): 0x6CF3E9, 0x9E31B4, 0xA654C9, 0xAB4AB1, 0xABF2B1
```

这些是**所有**带同样位移的写入点，绝大多数属于无关类（同一个偏移量在很多
结构里都出现）。**仅凭偏移无法确定哪一个作用于我们的两个对象**——这正是
前面几轮反复出错的原因。

#### 结论：静态扫描到此为止

继续按偏移搜索只会得到一堆无关候选。要确定真正的推进者，必须**动态定位**：

1. 在目标对象上设置**硬件写断点**（`Dr0`–`Dr3` + `Dr7`），地址取
   `obj2+0x1A0` 与 `obj1+0x120`，命中时读取 `Eip` 即得写入指令；
2. 或者用 `VirtualProtect` + 单步陷阱逐个排除候选点。

两者都需要在当前进程里接管调试寄存器或改页属性，属于**进程内调试**范畴，
比之前的只读采样复杂一档，但这是唯一能确定性回答"谁把它写成 5"的方法。

#### 当前的确定事实（可直接用作断言）

| 事实 | 值 | 来源 |
|---|---|---|
| `[lobby+0x1F4]` | 恒为 1 | 200 Hz × 5 s 采样，921 次全 1 |
| `0xBAE1AC`（写 2） | 从未执行 | `1F4` 从不出现 2，且无跳转指向它 |
| `obj1 = [lobby+0x1F8]` | `+0x120` = **3**（需 2） | 实测 |
| `obj2 = [lobby+0x1FC]` | `+0x1A0` = **5**（需 4） | 实测 |
| `0xBAE810` 初始化 | `+0x1A0` = 0 | 反汇编 |
| `0xBBAD40` 成功时 | `+0x1A0` = 1 | 反汇编 |

#### 下一步

用硬件写断点定位 `obj2+0x1A0` 的写入指令。若确认它由某个服务应答驱动，
则补齐应答；若由定时器驱动，则需要更长的观察窗口。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.52"),
                         ("HANDOFF-CURRENT.md", "### 15.40")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.52", "### 15.40")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
