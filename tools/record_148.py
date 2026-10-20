"""Record round 185: the 148-byte cleanup is fully accounted for once the two stray pushes are counted."""
from pathlib import Path

TEXT = """
### 12.200 关键：`add esp, 0x94` 的 148 字节完全对上——`0xB754C0` 那两个 push 留在了栈上（2026-10-26 19:2x）

#### 原始字节

```
0xC73F70..A0:
FF 0F B7 D0 8B 43 04 52 81 EC 84 00 00 00 8B FC B9 21 00 00 00
50 F3 A5 E8 93 D4 F3 FF 8B 4D FC 81 C4 94 00 00 00 5F 5E 33 CD 5B …
```

#### 反汇编（从 `0xC73F74` 起的干净边界）

```asm
0xC73F74  8B 43 04        mov eax, dword ptr [ebx+4]     ; socket
0xC73F77  52              push edx                        ; ① 4 字节
0xC73F78  81 EC 84 00 00 00  sub esp, 0x84               ; ② 132 字节
0xC73F7E  8B FC           mov edi, esp
0xC73F80  B9 21 00 00 00  mov ecx, 0x21                   ; 33 个 dword
0xC73F85  50              push eax                        ; ③ 4 字节
0xC73F86  F3 A5           rep movsd
0xC73F88  E8 93 D4 F3 FF  call 0xBB1420
0xC73F8D  8B 4D FC        mov ecx, [ebp-4]
0xC73F90  81 C4 94 00 00 00  add esp, 0x94                ; ★ 148 字节
```

#### 差额的来源：`0xC73F66` 与 `0xC73F67` 的两个 push

回看 `0xC73F63` 之前：

```asm
0xC73F63  8B 4D 10        mov ecx, dword ptr [ebp+0x10]   ; 长度
0xC73F66  51              push ecx                        ; ★ 4 字节
0xC73F67  56              push esi                        ; ★ 4 字节
0xC73F68  8B CF           mov ecx, edi
0xC73F6A  8B F0           mov esi, eax
0xC73F6C  E8 4F 15 F0 FF  call 0xB754C0
```

**而 `0xB754C0` 是 `mov ax,[ecx+0x84]; ret`——它以 `ret`（无立即数）结束，
不清理这两个 push。**

**所以那两个 push 的结果留在了栈上。**

#### 加总

```
push ecx  (0xC73F66)    4
push esi  (0xC73F67)    4
push edx  (0xC73F77)    4
sub esp,0x84 (0xC73F78) 132
push eax  (0xC73F85)    4
                       ---
合计                   148 = 0x94     ✔
```

**与 `add esp, 0x94` 完全吻合，不再有 8 字节差额。**

#### 于是 `0xBB1420` 的真实参数布局（从 `esp` 最低处往上）

| 偏移 | 内容 |
|---|---|
| `[esp+0x00]` | **socket**（最后一次 push） |
| `[esp+0x04]` | **132 字节块**（序列化后的缓冲区副本） |
| `[esp+0x88]` | `edx`（`0xB754C0` 返回的 word） |
| `[esp+0x8C]` | **`esi`**（即 `0xC73F30` 的参数 2，缓冲区指针） |
| `[esp+0x90]` | **`ecx`**（即 `0xC73F30` 的参数 3，长度） |

**对应到 `0xBB1420` 的形参（`ebp+8` 起）：**

- `[ebp+8]` = socket
- `[ebp+0xC]` = 132 字节块的**第一个 dword**
- `[ebp+0x90]` = word
- `[ebp+0x94]` = 缓冲区指针
- `[ebp+0x98]` = 长度

#### 这解开了 §12.199 的疑点

**`sin_addr = [ebp+0xC]` 确实是那 132 字节块的第一个 dword。**

**但真正的 IP 地址应当在 `[ebp+0x94]`（缓冲区指针）所指向的数据里，
或者这个 `0xBB1420` 并不是普通 `sendto` 的包装，而是一层把"132 字节块"
当作自定义头、把缓冲区和长度放在后面的封装。**

**结合 `[ebp+0x90]` 那个 word（来自 `0xB754C0`）与 `[ebp+0x98]` 的长度，
这更像是"带自定义头的发送函数"，内部先拼头再调真正的 `sendto`。**

#### 下一步

**重新审视 `0xBB1420` 的前半段**（`0xBB1420`–`0xBB1453`），确认外层那个
`cmp edi,-1` 检查的对象，以及 `[ebp+0x90]`/`[ebp+0x94]`/`[ebp+0x98]` 的用途。

**这次有了准确的参数布局，解读会可靠得多。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.200"),
                         ("HANDOFF-CURRENT.md", "### 16.88")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.200", "### 16.88")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
