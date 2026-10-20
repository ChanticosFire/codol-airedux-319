"""Record round 176: the send wrapper bails with a negative value when the socket is -1."""
from pathlib import Path

TEXT = """
### 12.191 ★★★ `0xBB1420` 的前置检查：socket 为 `-1` 时直接返回负数（2026-10-26 14:5x）

#### 函数开头

```asm
0xBB1420  push ebp / mov ebp,esp
0xBB1423  sub esp, 0x14
0xBB1426  mov eax, [0xE3F240]
0xBB142B  xor eax, ebp
0xBB142D  mov [ebp-4], eax
0xBB1430  push esi
0xBB1431  mov esi, dword ptr [ebp+0x94]    ; 一个远参数
0xBB1437  push edi
0xBB1438  mov edi, dword ptr [ebp+8]        ; ★ 参数 1
0xBB143B  83 FF FF                       cmp edi, -1                ; ★ 是否 INVALID_SOCKET
0xBB143E  75 13                          jne 0xBB1453               ; 不是 -> 继续
0xBB1440  8D 47 F7                       lea eax, [edi-9]           ; eax = -10
0xBB1443  5F / 5E                        pop edi / pop esi
0xBB1445  8B 4D FC                       mov ecx, [ebp-4]
0xBB1448  33 CD                          xor ecx, ebp
0xBB144A  E8 C0 AD 08 00                 call 0xC3C20F
0xBB144F  8B E5 / 5D / C3               mov esp,ebp / pop ebp / ret  ; ★ 返回 -10
```

**当参数 1 等于 `-1`（`INVALID_SOCKET`）时，函数直接返回 `-10`。**

`-10` 是负数，**而 `0xBBA7D4` 是 `jle`（小于等于 0 即失败）**——
所以这条路径会立刻把状态写成 5。

#### 正常路径的 sockaddr 构造

```asm
0xBB1453  8B 95 90 00 00 00      mov edx, dword ptr [ebp+0x90]
0xBB1459  8B 4D 0C               mov ecx, dword ptr [ebp+0xC]
0xBB145C  33 C0                  xor eax, eax
0xBB145E  89 45 EC               mov [ebp-0x14], eax        ; sockaddr 清零
0xBB1461  89 45 F0               mov [ebp-0x10], eax
0xBB1464  89 45 F4               mov [ebp-0xC], eax
0xBB1467  89 45 F8               mov [ebp-8], eax
0xBB146A  B8 02 00 00 00         mov eax, 2                  ; ★ AF_INET
0xBB146F  52                     push edx                     ; 长度
0xBB1470  66 89 45 EC            mov word ptr [ebp-0x14], ax  ; sin_family = AF_INET
0xBB1474  89 4D F0               mov dword ptr [ebp-0x10], ecx ; ★ sin_addr
```

**`ecx`（`[ebp+0xC]`，参数 2）被写入 `sockaddr.sin_addr`。**

**所以参数 2 是 IP 地址，而端口应当随后写入 `sin_port`（`[ebp-0x12]`）。**

#### 状态 5 的两种可能，现在只剩两条

| 可能 | 表现 |
|---|---|
| **socket 是 `-1`** | 返回 `-10`，`jle` 判失败 |
| **`sendto` 本身失败** | 返回 `SOCKET_ERROR`（-1），同样 `jle` 判失败 |

**两者都会导致状态 5，且都与消息内容无关。**

#### 下一步

**继续反汇编 `0xBB1480` 之后**，找到 `sendto` 的实际调用与端口写入位置。

**同时值得测量：`[serverlist+0x80]` 的 dword（不是 word）是否是那个 socket 句柄。**
**若它是 0 或 `-1`，就说明 socket 从未创建。**

**这是下一步最关键的一次读取——一个 dword 就能判定。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.191"),
                         ("HANDOFF-CURRENT.md", "### 16.79")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.191", "### 16.79")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
