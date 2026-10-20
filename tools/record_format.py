"""Record round 163: the message layout starts with a type byte then a word."""
from pathlib import Path

TEXT = """
### 12.178 ★★★ 消息格式：`[1 字节类型][2 字节 word]…`，类型范围 `0x14`–`0x1D`（2026-10-26 06:5x）

#### `0xBC1D20` 的解析流程

```asm
0xBC1D20  push ebp / mov ebp,esp / push ecx
0xBC1D24  mov eax, [ebp+0x10]              ; 参数 4（长度？）
0xBC1D28  mov ebx, [ebp+8]                  ; 参数 1（数据指针）
0xBC1D2C  mov esi, [ebp+0x14]               ; 参数 5（读位置游标）
0xBC1D30  mov edi, [ebp+0xC]                ; 参数 2
0xBC1D33  push 1                            ; ★ 读 1 字节
0xBC1D38  lea ecx, [ebp+0x17]               ; 输出到栈
0xBC1D40  mov [esi], eax                     ; 保存偏移
0xBC1D42  call 0xB78450                      ; ★ 通用"读 N 字节"函数
0xBC1D4A  test al, al
0xBC1D4C  je 0xBC1D5A                        ; 读失败
0xBC1D51  mov dl, [ebp+0x17]                 ; 取首字节
0xBC1D54  mov [eax], dl                      ; ★ this[0] = 类型
0xBC1D56  mov al, 1

0xBC1D61  cmp cl, 0x14                        ; ★ 类型 >= 0x14
0xBC1D64  jb 0xBC1E4D                         ; 小于 -> 失败返回
0xBC1D6A  cmp cl, 0x1D                        ; ★ 类型 <= 0x1D
0xBC1D6D  ja 0xBC1E4D                         ; 大于 -> 失败返回

0xBC1D79  push 2                              ; ★ 再读 2 字节
0xBC1D7B  lea edx, [ebp+0x14]
0xBC1D83  call 0xB78450
0xBC1D8F  mov ax, word [ebp+0x14]
0xBC1D96  mov word [ecx+2], ax                ; ★ this[2] = word

0xBC1DA3  cmp word [ecx+2], 2                 ; ★ 该 word 是否 == 2
0xBC1DA8  je 0xBC1E0F                          ; == 2 -> 走专用分支
0xBC1DAE  … push 2 / call 0xB78450            ; 否则继续读
```

#### 得到的信息

1. **`0xB78450` 是通用的"读 N 字节"函数**——参数含长度与输出缓冲，
   返回 `al = 1` 表示成功；
2. **消息首字节是类型码，合法范围 `[0x14, 0x1D]`**——`0x15` 在范围内；
3. **第二个字段是 2 字节 word**，存到 `this[2]`；
4. **`this[2] == 2` 时走一条专用分支（`0xBC1E0F`）**，否则继续读更多字段。

#### 对构造 `0x15` 消息的意义

`0xBBAB5E` 要求 `0xBC1D20` 返回 1——**即类型在范围内且首两个字段能读出**。
`0xBBAB6B` 又要求 `0xBC1CB0` 返回 `this[0] == 0x15`。

**所以最小可行消息至少是 3 字节**：

```
15 XX XX        （类型 0x15 + 一个 2 字节 word）
```

**而 `this[2]` 那个 word 很可能是"条目数"——若设为 0，后面的循环不执行；
若设为 N>0，则还要跟上 N 条记录。**

#### 下一步

**反汇编 `0xBC1E0F`**（`word == 2` 的专用分支）与跟随 `0xBC1DAE` 之后的循环，
弄清：

1. `this[2]` 那个 word 的确切语义（条目数？版本？）；
2. 如果它是条目数，单条记录的结构是什么；
3. `0xBC1CB0`（返回 `this[0]` 的访问器）确认。

**然后就能在 `lobby_udp.py` 里构造一条最小 `0x15` 消息并观察客户端状态是否推进到 4。**

**注意**：先试 `15 00 00`（word = 0）——若只要求类型匹配，
这可能是最小可用的消息；若客户端还要求条目数 > 0，再补。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.178"),
                         ("HANDOFF-CURRENT.md", "### 16.66")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.178", "### 16.66")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
