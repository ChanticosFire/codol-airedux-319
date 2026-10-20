"""Record round 172: the send function takes type, buffer, length and dispatches by type."""
from pathlib import Path

TEXT = """
### 12.187 `0xC73F30` 的参数顺序与分派（2026-10-26 12:5x）

#### 函数开头

```asm
0xC73F30  push ebp / mov ebp,esp
0xC73F33  sub esp, 0x8C
0xC73F39  mov eax, [0xE3F240]          ; cookie
0xC73F40  mov [ebp-4], eax
0xC73F43  push ebx / push esi
0xC73F45  mov esi, [ebp+0xC]            ; ★ 参数 2 -> esi
0xC73F48  push edi
0xC73F49  mov edi, [ebp+8]              ; ★ 参数 1 -> edi
0xC73F4C  lea eax, [ebp-0x88]
0xC73F52  mov ebx, ecx                   ; this
0xC73F54  push eax
0xC73F55  mov ecx, edi
0xC73F57  call 0x853A10                  ; ★ 以参数 1 为 this 取某对象
0xC73F5C  mov ecx, eax
0xC73F5E  call 0xB770A0                  ; 转换/取值
0xC73F63  mov ecx, [ebp+0x10]           ; ★ 参数 3
0xC73F66  push ecx
0xC73F67  push esi                       ; 参数 2（数据）
0xC73F68  mov ecx, edi
0xC73F6A  mov esi, eax                   ; 保存中间结果
0xC73F6C  call 0xB754C0                  ; ★ 另一步（返回 word）
0xC73F71  movzx edx, ax
0xC73F74  mov eax, [ebx+4]
0xC73F77  push edx
0xC73F78  sub esp, 0x84
```

#### 参数顺序已确定

`__thiscall`：`ecx` 是 `this`，栈上是 `[ebp+8]`、`[ebp+0xC]`、`[ebp+0x10]`。

**而 §12.186 记录的调用是：**

```asm
0xBBA7C7  push edx      ; 长度    -> 第 3 个压栈 = [ebp+0x10]
0xBBA7CE  push edx      ; 数据    -> 第 2 个压栈 = [ebp+0xC]
0xBBA7CF  push edi      ; 类型    -> 第 1 个压栈 = [ebp+8]
```

**所以：参数 1 = 类型，参数 2 = 数据，参数 3 = 长度。**

#### 它按类型分派

`0xC73F55` 用**参数 1（类型）**去调 `0x853A10`，再经 `0xB770A0` 转换。

**这看起来是"按消息类型取得对应的处理器/编解码器"。**

**随后 `0xC73F6C call 0xB754C0` 返回一个 word，被 `movzx edx,ax` 提升为 dword
并压栈——这多半是要发给网络的某个字段（端口或长度）。**

#### 对状态 5 的意义

**发送函数的返回值由末尾决定。** 还需要看 `0xC73F78` 之后的部分，
才能知道它在什么情况下返回 0 或与长度不符。

**但已经可以确定一件事：类型 3 若不在 `0x853A10` 的支持列表里，
取到的对象可能为空，后续操作就会失败——这会直接导致状态 5。**

**这也解释了为什么状态 5 与我们发的内容无关：
客户端收到回复后要回发一条类型 3 的确认，而类型 3 在这条路径上走不通。**

**下一步**：反汇编 `0xC73F78`–`0xC73FE0`，并检查 `0x853A10` 支持哪些类型。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.187"),
                         ("HANDOFF-CURRENT.md", "### 16.75")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.187", "### 16.75")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
