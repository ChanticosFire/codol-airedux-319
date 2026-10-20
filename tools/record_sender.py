"""Record round 170: 0xBBA760 serialises and sends rather than validating."""
from pathlib import Path

TEXT = """
### 12.185 ★★★ `0xBBA760` 是"序列化 + 发送"，不是验证器（2026-10-26 11:5x）

#### 代码

```asm
0xBBA760  push ebp / mov ebp,esp
0xBBA763  sub esp, 0x518                    ; 1304 字节栈帧
0xBBA769  mov eax, [0xE3F240]               ; cookie
0xBBA770  mov [ebp-4], eax
0xBBA773  mov eax, [ebp+8]                  ; 参数 1：数据指针
0xBBA779  mov edi, [ebp+0xC]                ; 参数 2：类型
0xBBA77C  mov esi, ecx                       ; this
0xBBA77E  push eax
0xBBA77F  lea ecx, [ebp-0x518]
0xBBA785  xor bl, bl                         ; 默认返回 0
0xBBA787  call 0xBC1C00                      ; 构造序列化器
0xBBA78C  lea ecx, [ebp-0x510]
0xBBA792  push ecx
0xBBA793  push 0
0xBBA795  push 0x508                         ; 缓冲 1288 字节
0xBBA79A  lea edx, [ebp-0x50C]
0xBBA7A0  push edx
0xBBA7A1  lea ecx, [ebp-0x518]
0xBBA7B1  call 0xBC1C20                      ; ★ 序列化
0xBBA7B6  cmp al, 1
0xBBA7B8  jne 0xBBA7F3                       ; 失败 -> 返回 0
0xBBA7BA  mov edx, [ebp-0x510]
0xBBA7C0  mov ecx, [esi]                     ; ★ vtable
0xBBA7C2  mov eax, [ecx]
```

#### 它不是校验，而是打包外发

`0xBC1C00` / `0xBC1C20` 与 §12.132 里 `0xBBA1F0` 用的是同一族函数
（`0xBC18E0`/`0xBC1900`/`0xBC1970`），**都是"把结构写入一个 1288 字节缓冲"**。

**随后 `mov ecx,[esi]` / `mov eax,[ecx]` 取 vtable——这是要调用虚方法的前奏，
即把缓冲发出去。**

**所以 `0xBBA760(this, data, type)` 的语义是"把 data 序列化后发送"。**

#### 这修正了对 `0xBBA8C0` 的理解

```asm
0xBBA8C0  lea eax, [ecx+4]       ; this+4
0xBBA8C5  push 3
0xBBA8C7  call 0xBBA760
0xBBA8CE  cmp bl, 1
```

**`0xBBA8C0` 是把 `this+4` 处的东西以类型 3 发送出去，并返回是否成功。**

**所以 `0xBBAAA1 call 0xBBA8C0` 之后判断的 `al`，
语义是"发送是否成功"，而不是"字段是否合法"。**

#### 于是状态 5 的含义需要修正

```
0xBBAAA1 call 0xBBA8C0    -> 发送 this+4（类型 3）
0xBBAAA6 test al, al
0xBBAAA8 jne 0xBBAAC7     -> 发送成功 -> 状态 2
0xBBAAAC 状态 5            -> 发送失败
```

**状态 5 = 发送失败；状态 2 = 发送成功。**

**我们的九字节回复让这个发送失败了——很可能是因为**
**它在 `this+4` 那个位置留下了不完整/非法的数据，导致序列化或后续发送出错。**

#### 注意参数不一致

`0xBBAA98` 把 136 字节复制到 `[ebx+0x114]`，而 `0xBBA8C0` 发送的是 `this+4`。

**两者不是同一块内存——说明 `0xBBAAA1` 发送的是对象头的另一部分，
而 `[ebx+0x114]` 是刚复制进来的列表数据，稍后才会被用到。**

**下一步**：继续反汇编 `0xBBA7C0` 之后，确认它到底调用哪个虚槽、
发送什么内容——这决定了"发送失败"的具体原因。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.185"),
                         ("HANDOFF-CURRENT.md", "### 16.73")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.185", "### 16.73")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
