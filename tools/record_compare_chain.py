"""Record the comparison that decides 0xBAF040 and hence [lobby+0x1F4]."""
from pathlib import Path

TEXT = """
### 12.26 判定链解析：`0xBAF040` 失败的比较条件（2026-10-23 01:4x）

#### `0xB77020` → `0xB76FD0`

```asm
0xB77020  lea ecx,[ebp-0x88]
0xB7703C  call 0xB76F10          ; 构造"当前对象"（内部调 0xBB10A0 初始化）
0xB77041  push eax
0xB77042  mov ecx, esi            ; 被检查的对象（lobby+0x6D0）
0xB77044  call 0xB76FD0           ; 比较
0xB7704C  test al, al
0xB7704E  sete al                 ; ★ 取反：比较返回 0 才算成功
```

#### `0xB76FD0` 的实际比较

```asm
0xB76FD0  mov edx, [ebp+8]              ; 临时对象
0xB76FD6  xor al, al                     ; 默认 0
0xB76FD8  cmp word ptr [edx+0x80], 0x17  ; 临时对象类型字段 == 23 ？
0xB76FE0  je 0xB76FE9                    ; 是 -> 保持 0 返回
0xB76FE2  mov eax, [ecx]                 ; 当前对象首字段
0xB76FE4  cmp eax, [edx]                 ; 与临时对象首字段比较
0xB76FE6  sete al                        ; 相等 -> 1
0xB76FE9  ret 4
```

因为外层 `0xB77020` 又做了一次 `sete`，最终成功条件是：

```
0xB76FD0 返回 0  =>  [临时+0x80] == 23  或  [当前][0] != [临时][0]
```

即 **`0xBAF040` 只在「类型是 23」或者「两个对象首字段不同」时返回成功**。

#### 实测值

```
[lobby+0x6D0]      = 15          （当前对象首字段）
[lobby+0x6D4]      = 0
[lobby+0x8A4]      = 22011       （数据块长度，16 位）
[lobby+0x8A8..+8B8] = c0 a8 01 03 00 00 00 00 00 00 00 00 fe ff ff ff
                    = 192.168.1.3, 0, 0, -2
```

当前对象首字段是 **15**，不是 23。所以成功与否取决于临时对象首字段是否**不等于** 15。

#### 解读

这个 `cmp word [edx+0x80], 0x17` 加上「首字段不等」的模式，像是**按类型过滤**：
调用方逐个取出某种列表项，用 `0x17`（23）标记"需要特殊处理"，否则只保留
与当前对象类型不同的那些。

结合 `[lobby+0x8A8]` 存的是 `192.168.1.3` 这类服务器地址，`0xBAF040` 很可能
在做**服务器条目筛选**——从一批候选里挑出与当前不同的那个。

#### 结论与下一步

`[lobby+0x1F4]` 停在 1 的直接原因是 `0xBAF040` 返回 0（失败），而失败发生在
上述比较。要让它成功，需要满足二者之一：

1. 临时对象的 `[+0x80]` 字段等于 **23**；
2. 两个对象的首字段（实测当前为 15）不相等。

这两者都由客户端内部状态决定，服务端能施加影响的入口是 `[lobby+0x8A8]`
那块服务器信息。因此下一步应：

1. 读 `[lobby+0x8A8]` 的**完整 136 字节**，确认除 IP 外的端口/会话字段；
2. 在 `0xBAF040` 上做一次性读取，记录临时对象的 `[0]` 与 `[+0x80]` 实测值；
3. 判断服务端下发的哪一项能改变这两个值。

第 2 步需要断点或 hook，比纯内存读取复杂；先从第 1 步的低成本读取开始。
"""


def main() -> None:
    root = Path(r"E:\GAME\COD\codol-airedux\319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.26"),
                         ("HANDOFF-CURRENT.md", "### 15.14")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.26", "### 15.14")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
