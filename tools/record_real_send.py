"""Record round 173: the real send is 0xBB1420, and 0x853A10 is just an identity getter."""
from pathlib import Path

TEXT = """
### 12.188 ★★★ 真正的发送点是 `0xC73F88 call 0xBB1420`；`0x853A10` 只是恒等 getter（2026-10-26 13:2x）

#### `0xC73F78` 之后

```asm
0xC73F78  81 EC 84 00 00 00      sub esp, 0x84
0xC73F7E  8B FC                 mov edi, esp
0xC73F80  B9 21 00 00 00         mov ecx, 0x21          ; ★ 33 个 dword = 132 字节
0xC73F85  50                     push eax
0xC73F86  F3 A5                  rep movsd               ; 复制到栈
0xC73F88  E8 93 D4 F3 FF         call 0xBB1420           ; ★ 真正的发送
0xC73F8D  8B 4D FC               mov ecx, [ebp-4]
0xC73F90  81 C4 94 00 00 00      add esp, 0x94
0xC73F96  5F                     pop edi
0xC73F97  5E                     pop esi
0xC73F9A  5B                     pop ebx
0xC73F9B  E8 6F 82 FC FF         call 0xC3C20F           ; cookie 校验
0xC73FA0  8B E5                  mov esp, ebp
0xC73FA2  5D                     pop ebp
0xC73FA3  C2 0C 00               ret 0xC                 ; 3 个参数
```

**`0xBB1420` 就是 §12.62 记录的 UDP `sendto` 包装。**

**它的返回值原样作为 `0xC73F30` 的返回值，进而被 `0xBBA7D6` 与序列化长度比较。**

#### `0x853A10` 是恒等函数

```asm
0x853A10  8B C1                 mov eax, ecx
0x853A12  C3                    ret
```

**它只是把 `ecx` 原样返回。**

**所以 `0xC73F55 mov ecx,edi` / `call 0x853A10` 等于"把类型值取回来"，
不是"按类型查表"。§12.187 的猜测被否定。**

#### 于是调用链完全确定

```
0xBBA760(this, data, type)
  └─ 0xBC1C20  序列化 data -> 缓冲，长度写入 [ebp-0x510]
  └─ vt+0x18 = 0xC73F30(this, type, 缓冲, 长度)
       └─ 0xB754C0  取端口（word）
       └─ rep movsd 复制 132 字节到栈
       └─ 0xBB1420  真正的 sendto
            └─ 返回实际发送字节数
  └─ 要求 sendto 返回值 == 序列化长度
```

#### 状态 5 的最可能原因

**`sendto` 返回的字节数与请求长度不符。**

**在 UDP 上，`sendto` 要么整包发出（返回完整长度），要么失败（返回 SOCKET_ERROR）。
所以"不符"基本等同于失败。**

**失败原因可能包括：**

- **目标地址无效**（`0xBB1420` 内部的 `sockaddr` 未正确设置）；
- **`0xB754C0` 取到的端口为 0 或非法**；
- **socket 状态异常**。

**注意 `0xB754C0` 取的是 `this+0x80` 处的 word（§12.82 记录其为端口 3074）。**

**若那个字段为 0，`sendto` 就会失败——这非常可能就是状态 5 的直接原因。**

#### 下一步

**反汇编 `0xBB1420`**，看它如何组装 `sockaddr`、从哪个字段取 IP 与端口、
以及失败时返回什么。

**同时可以测量**：在状态 5 出现时，读 `[serverlist+0x80]` 的 word 值，
看端口是否为 3074。

**后者更快——一个 word 的读取就能验证这个假设。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.188"),
                         ("HANDOFF-CURRENT.md", "### 16.76")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.188", "### 16.76")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
