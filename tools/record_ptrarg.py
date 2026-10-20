"""Record round 183: the first argument is a pointer, not a type value."""
from pathlib import Path

TEXT = """
### 12.198 ★★★ 修正：`0xC73F30` 的第一个参数是指针 `this+4`，不是类型值（2026-10-26 18:2x）

#### 原始字节核对

```
0xB754C0..D0: 66 8B 81 84 00 00 00 C3        mov ax,[ecx+0x84]; ret
0xB75440..50: 55 8B EC 66 8B 91 84 00 00 00 8B 45 08 66 3B 90
0xC73F43..6C: 53 56 8B 75 0C 57 8B 7D 08 8D 85 78 FF FF FF 8B D9 50 8B CF
              E8 B4 FA BD FF 8B C8 E8 3D 31 F0 FF 8B 4D 10 51 56 8B CF 8B F0 E8
0xBBA7C0..D2: 8B 0E 8B 01 8B 40 18 52 8D 95 F4 FA FF FF 52 57 FF D0
```

#### 压栈顺序重新推导

`0xBBA8C0`：

```asm
0xBBA8C1  lea eax, [ecx+4]     ; eax = this+4
0xBBA8C4  push eax              ; 第一次压栈 → 落到 [ebp+0xC]
0xBBA8C5  push 3                ; 第二次压栈 → 落到 [ebp+8]
0xBBA8C7  call 0xBBA760
```

**stdcall 从右往左压参，所以最后压的 `3` 是 `[ebp+8]`，先压的 `this+4` 是 `[ebp+0xC]`。**

`0xBBA760`：

```asm
0xBBA773  mov eax, [ebp+8]      ; eax = 3
0xBBA779  mov edi, [ebp+0xC]    ; ★ edi = this+4（指针）
0xBBA77E  push eax               ; 3 传给 0xBC1C00（序列化器）
0xBBA787  call 0xBC1C00
…
0xBBA7CF  push edi               ; ★ this+4 传给 0xC73F30 的第一个参数
0xBBA7D0  call eax
```

#### 于是矛盾消解

`0xC73F30` 的 `[ebp+8]` 是 `this+4`（指针），**不是 `3`**。

```asm
0xC73F49  mov edi, [ebp+8]      ; edi = this+4
0xC73F68  mov ecx, edi           ; ecx = this+4
0xC73F6C  call 0xB754C0          ; 读 [this+4+0x84] = [this+0x88]
```

**`[this+0x88]` 是合法地址（实测 `p+0x88 = 0x37D3BB44`），所以不会崩溃。**

**§12.192 关于"`ecx=3` 会读 `[0x87]`"的推断因此作废。**

#### 这改变了对整个发送链的理解

```
0xC73F30(this, ptr, buffer, length)
  ptr = this+4
  0xB754C0(ptr) -> 读 [ptr+0x84] -> 当作 word 返回
  该 word 与 buffer、length 一起传给 0xBB1420
```

**所以 `0xBB1420` 的第一个参数（socket）来自 `[this+4]`（`0xC73F74 mov eax,[ebx+4]`），
而 `0xB754C0` 返回的 word 是另一个参数。**

**两者的区分很重要：**

| 参数 | 来源 |
|---|---|
| socket | `[this+4]`（实测 11624） |
| 某个 word | `[this+0x88]` 的低 16 位 |

#### 下一步

**重新确认 `0xBB1420` 的完整参数列表**（它有 `ret` 而非 `ret N`，说明是 cdecl 或参数由调用方清理），
弄清那个 word 到底是端口还是别的。

**同时应重新审视"状态 5"的成因**：既然 socket 有效、地址读取也合法，
那失败只能来自 `sendto` 本身的返回值，或者序列化长度异常。

**最值得做的一次测量：在 `0xBB1420` 返回后立即读 `eax`。**
但那是寄存器，无法从外部读取——**替代方案是把 `0xBB14C5` 附近的返回值路径打桩**，
不过那属于代码修改，风险较高。

**更保守的做法**：读 `serverlist+0x8C` 的地址值（`0xFF00FF00`），
确认它是否为 `sin_addr` 的实际内容。若是，则 `sendto` 必然返回 `WSAEADDRNOTAVAIL`。
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.198"),
                         ("HANDOFF-CURRENT.md", "### 16.86")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.198", "### 16.86")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
