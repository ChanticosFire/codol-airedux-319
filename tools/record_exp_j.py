"""Record round 31: the server array is populated; pump has two exclusive paths."""
from pathlib import Path

TEXT = """
### 12.49 服务器数组是**非空**的；pump 有两条互斥路径（2026-10-23 09:0x）

#### 136 字节数据的真实来源

`0xBAE5DB` 起是一段紧凑循环：

```asm
0xBAE5DB  mov ecx, [ebx + 0x4D6C]     ; 当前索引
0xBAE5E1  inc ecx
0xBAE5E2  cmp ecx, [ebx + 0x4D68]     ; 与容量比较
0xBAE5E8  jae 0xBAE781                ; 超限 -> 走失败路径
0xBAE5F3  inc dword ptr [ebx + 0x4D6C]
0xBAE5F9  mov eax, [ebx + 0x4D6C]
0xBAE5FF  imul eax, eax, 0x88         ; ★ 每条 136 字节
0xBAE605  add eax, [ebx + 0x4D60]     ; ★ 数组基址
0xBAE60B  lea ecx, [ebp - 0x658]
0xBAE611  push eax
0xBAE612  call 0xB753C0               ; 复制该条目
```

**`0x88 = 136` 正是之前追了很久的那个"136 字节"**——它不是加密密钥、不是
服务器地址块，而是这个数组里的一条记录。

#### 数组实测非空

```
lobby = 0x37C988A0
+0x4D60 base = 0x37C8CF08
+0x4D64      = 1
+0x4D68 cap  = 1        <- 容量 1
+0x4D6C idx  = 0
首条 136 字节 = 7f 00 00 01 00 00 …   <- 127.0.0.1
```

**`svc71/task4` 的应答被接受了**——数组里确实有一条 `127.0.0.1` 的服务器记录。
所以"应答形状不对"这个怀疑可以排除。

#### pump 的两条互斥路径

| 路径 | 位置 | 写入 `[lobby+0x1F4]` |
|---|---|---|
| 失败 | `0xBAE781` → `0xBAE790` 循环 → `0xBAE7AA` | **1** |
| 成功 | `0xBAE180` → `0xBAE1A7` `call 0xC699B0` → `0xBAE1AC` | **2** |

`0xBAE7AA` 那条是**无条件**写 1：`jbe 0xBAE7AA` 在 `[ebx+0x18] <= 0` 时直接跳过去写，
否则先遍历 `[ebx+0x18]` 个元素再**同样**走到 `0xBAE7AA` 写 1。

而 `0xBAE1AC` 写 2 也是无条件的——只要执行流到达就写。

**所以我们走的是失败路径，需要让执行流改走 `0xBAE180` 那条。**

#### 尚未确定的关键点

`0xBAE180` 之前是这段（此前 dump 过，含对齐错位）：

```asm
0xBAE183  mov esi, eax
0xBAE18D  mov edx, [edx + 0xC]
0xBAE190  push eax
0xBAE191  call edx                    ; 虚调用
0xBAE193  mov ecx, [ebx + 0x1F0]      ; 大厅连接对象（实测非空）
0xBAE199  lea eax, [ebx + 0x184]
0xBAE19F  push eax
0xBAE1A0  push ecx
0xBAE1A1  lea ecx, [ebx + 0x1A0]
0xBAE1A7  call 0xC699B0
0xBAE1AC  mov dword ptr [ebx + 0x1F4], 2
```

要到达这里必须先满足进入 `0xBAE180` 分支的条件，而该条件尚未定位
（`0xBAE180` 处字节错位，反汇编要从更早的边界开始）。

#### 下一步

从 `0xBAE100` 之前的正确指令边界往后解，找出跳入 `0xBAE180` 的分支条件；
重点关注 `0xBAE140`…`0xBAE180` 之间的比较指令。若该条件依赖网络数据，
则要补对应的服务应答；若依赖客户端内部状态，则要找到写该状态的地方。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.49"),
                         ("HANDOFF-CURRENT.md", "### 15.37")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.49", "### 15.37")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
