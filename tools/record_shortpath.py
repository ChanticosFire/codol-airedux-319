"""Record round 164: word 1 or 2 takes the short path through a single handler."""
from pathlib import Path

TEXT = """
### 12.179 ★★★ `this[2]` 为 1 或 2 时走短路径，只调用一次 `0xB75720`（2026-10-26 07:2x）

#### 两条路径

**`0xBC1DA3` 的判断：**

```asm
0xBC1DA3  cmp word ptr [ecx+2], 2
0xBC1DA8  je 0xBC1E0F                ; == 2 -> 短路径
```

**`0xBC1DF8` 的补充判断：**

```asm
0xBC1DF5  mov ecx, [ebp-4]
0xBC1DF8  cmp word ptr [ecx+2], 1
0xBC1DFD  je 0xBC1E0F                ; == 1 -> 同样去短路径
0xBC1DFF  mov edx, [ebp+0x10]
0xBC1E03  mov [esi], edx
0xBC1E06  xor al, al                  ; 其他值 -> 返回 0（失败）
0xBC1E0C  ret 0x10
```

**所以 `this[2]` 只能是 1 或 2，否则解析失败。**

#### 短路径 `0xBC1E0F`

```asm
0xBC1E0F  test al, al
0xBC1E11  je 0xBC1E29
0xBC1E13  mov eax, [esi]
0xBC1E15  push esi
0xBC1E16  push eax
0xBC1E17  push edi
0xBC1E18  push ebx
0xBC1E19  add ecx, 4                  ; ★ this + 4
0xBC1E1C  call 0xB75720               ; ★ 唯一的处理器
0xBC1E21  test al, al
0xBC1E23  je 0xBC1E29
0xBC1E25  mov al, 1                    ; 成功
0xBC1E29  xor al, al
```

**只有一次 `call 0xB75720`，然后返回 `al=1`。**

#### 常规路径（`this[2]` 不是 1 或 2）

反而不成立——**因为 `0xBC1DF8` 已经把它限制为 1 或 2**。

**所以 `0xBC1DB0` 之后那段（读 2 字节 + 读 1 字节 + `0xB75500`）
属于另一条分支（`0xBC1DA8` 之前的判断），不适用于本条路径。**

#### 因此最短合法消息

```
[类型 0x15] [word = 1 或 2] [0xB75720 需要的数据]
```

**若 `0xB75720` 需要的数据量很小（例如一个字符串或一个定长结构），
那么一条 `0x15` 消息可能只需要十几个字节。**

#### 下一步

**反汇编 `0xB75720`**，看它从数据里读什么、读多少字节。

**这直接决定"构造一条能被接受的最小 0x15 消息"需要多少字节。**

**然后就能在 `lobby_udp.py` 里构造它并实测。**

**注意**：`0xBC1E19 add ecx,4` 说明 `0xB75720` 的输出目标是 `this+4`——
即解析后的数据从 `this+4` 开始存放。**`this[4..]` 就是条目数据区。**
"""


def main() -> None:
    root = Path("E:/GAME/COD/codol-airedux/319")
    for name, marker in (("PROJECT_STATUS.md", "### 12.179"),
                         ("HANDOFF-CURRENT.md", "### 16.67")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        body = TEXT if name == "PROJECT_STATUS.md" else TEXT.replace("### 12.179", "### 16.67")
        if marker in text:
            print(f"{name}: already has {marker}")
            continue
        with path.open("a", encoding="utf-8") as stream:
            stream.write(body)
        print(f"{name}: appended {len(body)} chars")


if __name__ == "__main__":
    main()
