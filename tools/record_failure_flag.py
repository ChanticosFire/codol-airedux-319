"""Record that [lobby+0x1F4]=1 means failure, not initial state."""
from pathlib import Path

TEXT = """
### 12.29 ★★ `[lobby+0x1F4]=1` 是失败标志，不是初始状态（2026-10-23 02:0x）

#### 补齐状态机的全部写入点

之前的扫描只匹配 `mov dword [addr], imm32`（`C7 05`），漏掉了寄存器形式。
`tools/find_stores.py` 覆盖 `A3`、`89 /r`、`01 /r`、`09 /r` 等 16 种编码后，
`[0xE59D20]` 的写入点从 3 处增加到 **6 处**：

| 地址 | 形式 | 写入值 |
|---|---|---|
| `0x6216B9` | `mov [addr], edx` | **3 或 5** |
| `0x6216E9` | `mov [addr], 0` | 0 |
| `0x62171C` | `mov [addr], eax` | 1 |
| `0x6217BF` | `mov [addr], 6` | 6 |
| `0x6217D0` | `mov [addr], 4` | 4 |
| `0x621A00` | `mov [addr], edi` | 视 edi |

#### `0x6216B9` 解开了状态 3/5 的来源

```asm
0x6216AD  cmp byte ptr [ebp + 8], dl
0x6216B2  setne dl                     ; dl = (参数 != 0)
0x6216B5  lea edx, [edx + edx + 3]     ; edx = 3 或 5
0x6216B9  mov dword [0xE59D20], edx
0x6216BF  call 0xBAD800                ; 立刻调用 pump
```

即：状态 **3** 或 **5** 由某个布尔参数决定，写完**立即**进入 pump。
我们在 5，说明该参数非零。

#### 写 1 的两处都在失败分支

```asm
0xBAE735  call 0xBBAD40                ; 处理数据块
0xBAE73A  cmp byte ptr [ebp - 0x988], 0
0xBAE741  mov byte ptr [ebp - 0x986], al   ; 保存返回值
0xBAE747  jne 0xBAE758                 ; 成功 -> 跳过
0xBAE749  call 0xBA4B20
0xBAE74E  mov dword [ebx + 0x1F4], 1   ; ★ 失败才写 1
0xBAE758  cmp byte ptr [ebp - 0x986], 0
0xBAE75F  jne 0xBAE770                 ; 成功 -> 跳过
0xBAE761  call 0xBA4B20
0xBAE766  mov dword [ebx + 0x1F4], 1   ; ★ 又一次
```

**关键修正**：`[lobby+0x1F4]` 的 **1 表示"处理失败"**，而不是"稳定的初始值"。
之前把它当成正常状态、试图从 1 推进到 2，方向就错了——正确的问题是
**为什么 `0xBBAD40` 失败**。

#### 失败原因下沉到 `0xBBA760`

```asm
0xBBAD40  mov ebx, ecx
0xBBAD46  cmp dword [ebx + 0x1A0], 0
0xBBAD4F  mov eax, [ebp + 8]           ; 参数1
0xBBAD52  test eax, eax
0xBBAD54  je 0xBBADAB                  ; 参数1 为 0 -> 失败
0xBBAD58  mov [ebx], eax               ; 保存参数1
0xBBAD6B  mov ecx, 0x22                ; 34 dwords
0xBBAD70  rep movsd                    ; 复制 136 字节
0xBBAD7D  call 0xBBAF00
0xBBAD86  call 0xBBA8A0                ; ★ 判定
0xBBAD8B  cmp al, 1
0xBBAD8D  jne 0xBBADCD                 ; != 1 -> 失败
0xBBAD95  mov dword [ebx + 0x1A0], 1   ; 标记已处理
0xBBADA4  mov al, 1
```

`0xBBA8A0` 进一步只是转发：

```asm
0xBBA8A0  push ebx
0xBBA8A1  lea eax, [ecx + 4]
0xBBA8A4  push eax                     ; 参数2 = this+4
0xBBA8A5  push 0                       ; 参数1 = 0
0xBBA8A7  call 0xBBA760                ; ★ 真正的实现
0xBBA8AE  cmp bl, 1
0xBBA8B1  jne 0xBBA8B8
0xBBA8B3  call 0xBA4B20
0xBBA8B8  mov al, bl
```

`0xBBA760(this, 0, this+4)` 的形式是典型的 **bdReference key-value 查询**
（同族的 `0xBBA8C0` 传 3、`0xBBA8E0` 传 2，都是不同 key 的变体）。

#### 这条链的意义

`0xBAD800`（pump）在某个阶段会调用 `0xBBAD40` 把一个 136 字节的数据块
登记进一个 key-value 容器；登记成功才把 `[lobby+0x1F4]` 推进到 2，
失败则写 1。

所以真正的问题是：**那个 136 字节的数据块登记失败**。它极可能就是
`[lobby+0x8A8]` 那块存储（之前测到 `192.168.1.3` 开头），也就是
**客户端期望从服务端拿到一份它不认识的服务器描述**。

#### 下一步

1. 反汇编 `0xBBA760`，确认它是按 key 查询还是插入，失败条件是什么；
2. 确认 `0xBBAD40` 的四个参数分别来自哪里（`0xBAE720` 一段可见
   `[ebx+0x1FC]`、`[ebx+0xC]` 等字段）；
3. 若能定位到期望的数据内容，则由服务端下发对应数据，`[lobby+0x1F4]`
   就能自然走到 2，pump 完成，`FE_state` 到 6，`onboarded` 被设置。

这条路径比之前所有尝试都更接近「服务端欠客户端一份数据」的假设，
与 M4 的协议优先方向一致。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.29"),
                         ("HANDOFF-CURRENT.md", "### 15.17")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.29", "### 15.17")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
