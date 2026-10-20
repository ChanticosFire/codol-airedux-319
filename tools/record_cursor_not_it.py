"""Record round 55: the cursor is already 0, so the append happens on the other branch."""
from pathlib import Path

TEXT = """
### 12.69 游标本来就是 0，重复追加来自另一条路径（2026-10-23 20:0x）

#### 测到的实际状态

```
[lobby+0x4D60] array base = 0x36C6EE50
[lobby+0x4D64]           = 1
[lobby+0x4D68] capacity  = 1
[lobby+0x4D6C] CURSOR    = 0        <- 本来就是 0，不是卡在末尾
[lobby+0x1F4]            = 1
obj1[0x120] = 3   cap = 5   idx = 5  <- obj1 列表已满
obj2[0x1A0] = 5
```

把游标重置为 0（值不变）后观察 120 秒，一切照旧。

**所以"游标未重置"这个假设被排除。**

#### 但这反而定位了真正的追加路径

`0xBAE4CB` 处是：

```asm
0xBAE4CB  cmp dword ptr [ebx + 0x4d6c], 0
0xBAE4D6  je 0xBAE52B          ; 游标 == 0 -> 跳到 0xBAE52B
```

**游标为 0 时，整段 `0xBAE4D8`–`0xBAE51A` 被跳过**，直接去 `0xBAE52B`。

而遍历循环 `0xBAE5DB` 的第一件事是：

```asm
0xBAE5DB  mov ecx, [ebx + 0x4d6c]    ; 0
0xBAE5E1  inc ecx                    ; 1
0xBAE5E2  cmp ecx, [ebx + 0x4d68]    ; 1 vs capacity 1
0xBAE5E8  jae 0xBAE781               ; ★ 1 >= 1 -> 直接跳去写 1
```

**游标 0、容量 1 时 `jae` 必然成立，所以那段循环根本不会追加任何条目。**

#### 结论：追加发生在 `0xBAE52B` 那条分支

```asm
0xBAE52B  lea eax, [ebx + 0x170]
0xBAE531  push eax
0xBAE532  push ecx
0xBAE533  mov eax, esp
0xBAE535  mov [ebp - 0x99c], esp
0xBAE53B  mov [eax], esi
0xBAE53D  test esi, esi
0xBAE53F  je 0xBAE54B
0xBAE541  add esi, 4
0xBAE544  push esi
0xBAE545  call dword ptr [0xCA8128]
0xBAE54B  mov ecx, [ebx + 0x1f0]        ; 大厅连接对象
0xBAE551  mov edx, [ecx]
0xBAE553  mov eax, [ebx + 0xc]
0xBAE556  mov edx, [edx + 0xc]          ; vtable+0xC
0xBAE559  push eax
0xBAE55A  call edx                       ; 虚调用
```

这是一次**基于 `[lobby+0x1F0]`（连接对象）的虚调用**，参数是 `[lobby+0xC]`。
它之后的 `0xBAE5DB` 才是数组遍历（此时已因 `jae` 退出）。

所以每帧的真实流程是：

```
pump
  ├─ 0xBAE276 Add(obj1, ...)     ← 追加一个条目（obj1 idx +1）
  ├─ 游标 == 0 → 跳过规范化段
  ├─ 0xBAE52B  对连接对象做一次虚调用
  ├─ 0xBAE5DB  遍历数组：游标 0→1，1 >= cap 1 → jae 0xBAE781
  └─ 0xBAE7AA  写 [lobby+0x1F4] = 1
```

**`0xBAE276` 的 `Add` 与后面的数组遍历是两件独立的事。** 前者每帧追加，
后者每帧立即因边界判断退出。

#### 修正 §12.68 的说法

上一轮把"重复追加"归因于"数组只有一条记录却被当流重放"。更准确的说法是：
**追加调用 `0xBAE276` 每帧无条件执行，其数据来自 pump 自己在 `0xBAE24E` 附近
构造的 136 字节副本，与数组遍历循环无关。** 数组遍历那段其实工作正常。

要问的问题因此变成：**`0xBAE276` 那个 `Add` 调用是否本应被某个条件保护？**

从 `0xBAE246 cmp dword [ebx+0x1F8], edi` / `je 0xBAE292` 看，它唯一的保护是
"obj1 指针非空"。也就是说**只要 obj1 存在，就每帧追加一次**——这在正常运行时
同样成立，说明正常流程依赖的是"`Add` 内部因状态不为 1 而快速返回"，
而不是外部条件。

**于是关键仍然是那个先有鸡还是先有蛋的问题**：`Add` 要求 `status == 1` 才追加，
而追加成功本应把 `status` 推到 2。现在 `status` 停在 3，两边都不成立。

下轮应当直接看 `Add` 成功路径里除了 `0xBBA569`（写 2）之外还做了什么，
以及 `0xBC1A50`（追加实现）返回值代表什么——很可能 `0xBC1A50` 一直返回假，
于是流程落到 `0xBBA5A5`，再由容量判断写 3。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.69"),
                         ("HANDOFF-CURRENT.md", "### 15.57")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.69", "### 15.57")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
