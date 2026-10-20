"""Record round 33: the two final gates are each off by exactly one."""
from pathlib import Path

TEXT = """
### 12.51 ★★★ pump 失败的确切原因：两个状态字段各差 1（2026-10-23 09:4x）

#### 用跳转映射代替推理

`tools/jump_map.py` 扫描 `0xBAD800` 函数体内所有跳转，得到的目标来源是：

| 目标 | 来源 |
|---|---|
| `0xBAE1AC`（写 2） | **无直接跳转** → 顺序执行（从 `0xBAE182` 直落） |
| `0xBAE781`（失败头） | `0xBAE5E8 jae`（容量比较） |
| `0xBAE7AA`（写 1） | `0xBAE786 jbe` |
| `0xBAE5DB`（遍历循环） | `0xBAE312 jne`、`0xBAE326 jne` |

**关键**：`0xBAE1AC` 没有任何跳转指向它，而唯一通往它的路径被
`0xBAE312` / `0xBAE326` 两个 `jne` 挡住。实测 `[lobby+0x1F4]` 恒为 1
（从不出现 2），这本身就证明 `0xBAE1AC` **从未执行**——与映射结果一致。

#### 被挡住的两个条件

```asm
0xBAE2DD  cmp byte ptr [ebp - 0x988], 0    ; 标志 1
0xBAE2E4  je 0xBAE7B4                       ; 0 -> 直接跳结尾（连 1 都不写）
0xBAE2EA  cmp byte ptr [ebp - 0x989], 0    ; 标志 2
0xBAE2F1  je 0xBAE7B4
0xBAE2F7  cmp byte ptr [ebp - 0x986], 0    ; 标志 3
0xBAE2FE  je 0xBAE7B4

0xBAE304  mov ecx, [ebx + 0x1f8]
0xBAE30A  call 0xBBA1E0                     ; = [obj1 + 0x120]
0xBAE30F  cmp eax, 2
0xBAE312  jne 0xBAE5DB                      ; ★ 不等于 2 -> 遍历后写 1

0xBAE318  mov ecx, [ebx + 0x1fc]
0xBAE31E  call 0xBBA750                     ; = [obj2 + 0x1A0]
0xBAE323  cmp eax, 4
0xBAE326  jne 0xBAE5DB                      ; ★ 不等于 4 -> 遍历后写 1

0xBAE32C  …                                 ; 成功路径
```

两个 getter 都只有一条指令：

```asm
0xBBA1E0  mov eax, dword ptr [ecx + 0x120]   ; ret
0xBBA750  mov eax, dword ptr [ecx + 0x1a0]   ; ret
```

#### 实测：两个值各差 1

```
lobby = 0x36BEEC50
obj1 = [lobby+0x1F8] = 0x38004F48
    [obj1 + 0x120] = 3     需要 2      <- 差 1
obj2 = [lobby+0x1FC] = 0x380050C0
    [obj2 + 0x1A0] = 5     需要 4      <- 差 1
[lobby+0x1F4] = 1
```

**两个判定条件都只差 1**。这不是"数据缺失"，而是**状态尚处于"进行中"
（3 / 5）而未到"完成"（2 / 4）**。

#### 这两个字段的含义推断

`obj2` 就是 `0xBAE810` 构造的那个 440 字节容器（`[lobby+0x1FC]`），而
`0xBAE810` 会把 `+0x1A0` 初始化为 **0**（§12.32 已确认）。现在它是 **5**，
说明它被某段代码推进过：`0 → … → 5`，而 pump 期望 **4**。

同理 `obj1`（`[lobby+0x1F8]`）的 `+0x120` 从初始值被推到 **3**，pump 期望 **2**。
两个对象各自是一个小状态机，**它们都还差最后一步**。

#### 为什么只差一步

`0xBAE2DD` 那三个 `cmp byte [ebp-0x988/0x989/0x986], 0` 很可能是**超时/重试
计数**：本轮尚未满足时，被检查的三个标志中有一个为 0，于是直接跳到
`0xBAE7B4`（跳过写 1）；等标志都齐了才进入 `0xBAE304` 的状态比较。也就是说
**这段代码本身在等下一轮**，而下一轮里 `obj1/obj2` 的状态却没有继续推进。

#### 下一步（方向明确）

1. 找 `[obj2+0x1A0]` 的写者：在 `0xBBA*` 区搜索 `mov [reg+0x1A0], imm` 与
   `mov dword [ecx+0x1a0], r`，确定 5 是怎么写上的、以及谁该把它写成 4；
2. 同样找 `[obj1+0x120]` 的写者；
3. 若这两处推进依赖某个服务应答，则补齐该应答；若依赖定时器，则需延长观察
   窗口（此前最长只观察到 150 秒）。

第 1 条最直接，且这两个对象是容器类，写者应当集中在 `0xBBA` 段内。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.51"),
                         ("HANDOFF-CURRENT.md", "### 15.39")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.51", "### 15.39")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
