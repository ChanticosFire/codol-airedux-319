"""Record round 184: sin_port comes from the conversion call at 0xCA8550."""
from pathlib import Path

TEXT = """
### 12.199 `sin_port` 来自 `0xCA8550` 的返回值；`sin_addr` 来自参数 2（2026-10-26 18:5x）

#### 完整的 sockaddr 构造

```asm
0xBB1453  mov edx, dword ptr [ebp+0x90]   ; 远参数
0xBB1459  mov ecx, dword ptr [ebp+0xC]     ; ★ 参数 2
0xBB145C  xor eax, eax
0xBB145E  mov dword ptr [ebp-0x14], eax    ; sockaddr 共 16 字节，先清零
0xBB1461  mov dword ptr [ebp-0x10], eax
0xBB1464  mov dword ptr [ebp-0xC], eax
0xBB1467  mov dword ptr [ebp-8], eax
0xBB146A  mov eax, 2
0xBB146F  push edx                           ; 转换函数的参数
0xBB1470  mov word ptr [ebp-0x14], ax        ; sin_family = 2 (AF_INET)
0xBB1474  mov dword ptr [ebp-0x10], ecx      ; ★ sin_addr = 参数 2
0xBB1477  FF 15 50 85 CA 00   call dword ptr [0xCA8550]   ; ★ 端口转换
0xBB147D  mov ecx, dword ptr [ebp+0x98]
0xBB1483  push 0x10                           ; sockaddr 长度 = 16
0xBB1485  mov word ptr [ebp-0x12], ax         ; ★ sin_port = 转换结果
0xBB1489  lea eax, [ebp-0x14]
0xBB148C  push eax                             ; &sockaddr
0xBB148D  push 0                               ; flags
0xBB148F  push ecx                             ; 长度
0xBB1490  push esi                             ; 缓冲区
0xBB1491  push edi                             ; socket
0xBB1492  FF 15 18 85 CA 00   call dword ptr [0xCA8518]   ; sendto
```

#### 槽位对照（依据 §12.195 的解析）

| 槽位 | 目标 | 用途 |
|---|---|---|
| `0xCA8550` | `WS2_32.dll+0x19C20` | **端口字节序转换**（`htons` 之类） |
| `0xCA8518` | （未解析出模块归属） | **`sendto`** |

**`sin_addr` 直接取参数 2，没有经过转换——说明它本来就是网络序的 dword。**

#### 参数 2 究竟是什么

`0xBB1420` 由 `0xC73F88` 调用，压栈顺序是：

```asm
0xC73F77  push edx        ; edx = movzx(0xB754C0 的返回值)  ← word
0xC73F78  sub esp, 0x84    ; 分配 132 字节
0xC73F7E  mov edi, esp
0xC73F80  mov ecx, 0x21    ; 33 个 dword = 132 字节
0xC73F85  push eax          ; eax = [ebx+4]（socket）
0xC73F86  rep movsd          ; 复制 132 字节到 [edi]
0xC73F88  call 0xBB1420
```

**注意 `push eax` 发生在 `rep movsd` 之前，而 `rep movsd` 的目​标是 `esp` 当时的值。**

**所以布局是：**

```
[esp+0x00]  socket            （最后一次 push）
[esp+0x04]  132 字节结构        （sub esp,0x84 分配）
[esp+0x88]  word                （最先 push 的 edx）
```

**对应到 `0xBB1420` 的形参：**

- `[ebp+8]` = socket
- `[ebp+0xC]` = 132 字节结构的开头 → 即 `sin_addr` 的来源
- `[ebp+0x90]` / `[ebp+0x94]` / `[ebp+0x98]` 落在结构内部或之后

#### 一个待确认的矛盾

**若 `sin_addr` 来自那 132 字节结构的开头，而该结构是"序列化后的消息体"，
那把它当 IP 地址用显然不对。**

**更可能的解释是：`0xBB1420` 的形参顺序与我推断的不同——
那 132 字节结构不是参数，而是通过栈传递的一份数据副本，
真正的 IP 地址来自 `[ebp+0xC]` 之外的另一个槽。**

**要解决这一点，必须精确知道 `0xBB1420` 的 `ret` 形式**：
- 若是 `ret`（无立即数，参数由调用方清理），则参数数量由调用方决定；
- 若是 `ret N`，则 N/4 就是参数个数。

**§12.176 的记录显示它是 `ret`（`0x00bb1452 c3`）——所以参数由调用方清理，
无法直接得个数。**

**下一步**：从 `0xC73F88` 之后找 `add esp, ...` 来反推参数总字节数，
从而确定 `0xBB1420` 到底收几个参数。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.199"),
                         ("HANDOFF-CURRENT.md", "### 16.87")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.199", "### 16.87")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
